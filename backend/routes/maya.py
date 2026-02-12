from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
import os
import logging
import time

from models import get_db
from models.maya_models import MayaUser, MayaQueryLog
from routes.chat_endpoints import chat_with_avatars, ChatRequest as ChatEndpointRequest
from services.preset_service import preset_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maya", tags=["alex"])


class UserRegistration(BaseModel):
    name: str
    email: EmailStr
    position: str


class RegistrationResponse(BaseModel):
    success: bool
    existing_user: bool
    remaining_questions: int


class ChatRequest(BaseModel):
    message: str
    email: EmailStr
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    remaining_questions: int


def _reset_if_new_day(user: MayaUser, db: Session):
    today = date.today()
    if user.last_reset_date is None or user.last_reset_date != today:
        user.questions_today = 0
        user.last_reset_date = today
        user.updated_at = datetime.utcnow()
        db.flush()


def _get_remaining(user: MayaUser) -> int:
    if user.subscription_tier in ('standard', 'premium'):
        return 999
    return max(0, (user.questions_limit or 5) - (user.questions_today or 0))


@router.post("/register", response_model=RegistrationResponse)
async def register_user(req: UserRegistration, db: Session = Depends(get_db)):
    try:
        user = db.query(MayaUser).filter(MayaUser.email == req.email).first()

        if user:
            _reset_if_new_day(user, db)
            remaining = _get_remaining(user)
            db.commit()
            logger.info(f"Existing user login: {req.email}, remaining: {remaining}")
            return RegistrationResponse(success=True, existing_user=True, remaining_questions=remaining)

        user = MayaUser(
            email=req.email,
            name=req.name,
            position=req.position,
            questions_today=0,
            questions_limit=5,
            last_reset_date=date.today(),
            subscription_tier='free',
            subscription_status='active',
        )
        db.add(user)
        db.commit()
        logger.info(f"New user registered: {req.email}")
        return RegistrationResponse(success=True, existing_user=False, remaining_questions=5)

    except Exception as e:
        db.rollback()
        logger.error(f"Registration error for {req.email}: {e}")
        raise HTTPException(status_code=500, detail="Помилка реєстрації. Спробуйте пізніше.")


@router.post("/chat", response_model=ChatResponse)
async def chat_with_alex(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        user = db.query(MayaUser).filter(MayaUser.email == request.email).first()

        if not user:
            raise HTTPException(status_code=401, detail="Користувач не зареєстрований")

        tier = user.subscription_tier or 'free'

        if tier == 'free':
            _reset_if_new_day(user, db)
            if (user.questions_today or 0) >= (user.questions_limit or 5):
                db.commit()
                return ChatResponse(
                    reply="Ви досягли ліміту безкоштовних питань на сьогодні. Поверніться завтра або оформіть підписку для безлімітного доступу.",
                    remaining_questions=0,
                )

        preset_answer = preset_service.get_preset_answer(request.message)
        start_time = time.time()

        if preset_answer:
            reply = preset_answer
            logger.info(f"[PRESET] Served instant answer for: {request.message[:50]}...")
        else:
            logger.info(f"[API] Calling Claude for: {request.message[:50]}...")
            chat_req = ChatEndpointRequest(
                message=request.message,
                avatar="alex",
                conversation_history=[],
            )
            response = await chat_with_avatars(chat_req)
            reply = response.response

        response_time_ms = int((time.time() - start_time) * 1000)

        log_entry = MayaQueryLog(
            email=request.email,
            query_text=request.message,
            response_text=reply[:2000] if reply else None,
            response_time_ms=response_time_ms,
            session_id=request.session_id,
            user_tier=tier,
        )
        db.add(log_entry)

        if tier == 'free':
            user.questions_today = (user.questions_today or 0) + 1
            user.last_question_at = datetime.utcnow()
            user.updated_at = datetime.utcnow()

        db.commit()

        remaining = _get_remaining(user)
        logger.info(f"Chat processed for {request.email}, tier: {tier}, remaining: {remaining}")

        return ChatResponse(reply=reply, remaining_questions=remaining)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Alex chat error: {e}")
        raise HTTPException(status_code=500, detail="Вибачте, сталася помилка. Спробуйте ще раз.")


@router.get("/preset-stats")
async def get_preset_stats():
    return preset_service.get_stats()


@router.post("/reload-presets")
async def reload_presets():
    return preset_service.reload_presets()
