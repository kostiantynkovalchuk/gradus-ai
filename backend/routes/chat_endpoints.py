from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from typing import Optional, List
import os
import re
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date, timezone

from services.avatar_personalities import (
    detect_avatar_role,
    get_avatar_personality,
    AVATAR_METADATA
)
from services.rag_utils import (
    ingest_website,
    retrieve_context,
    extract_urls,
    is_ingestion_request,
    extract_company_name_from_url
)
from services.query_expansion import expand_brand_query
from config.models import CLAUDE_MODEL_TELEGRAM, CLAUDE_MODEL_WEBSITE, ALEX_CHAT_MODEL
from services.alex_memory import (
    load_memory_sync, format_memory_context,
    save_exchange_sync, extract_and_update_profile,
    PAID_TIERS, PROFILE_TRIGGER_EVERY,
)

logger = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/chat", tags=["chat"])

_FREE_DAILY_LIMIT = 5
_TRIAL_DAYS = 7


def _get_web_user_limits(email: str) -> dict:
    """
    Server-side rate limit check for web Alex chat.
    Returns:
      {"tier": str, "trial_expired": bool, "daily_limit_reached": bool}
    Queries maya_users for authoritative tier, then alex_user_profiles for counters.
    """
    result = {"tier": "free", "trial_expired": False, "daily_limit_reached": False}
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL", "")
        with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
            # Authoritative tier from maya_users
            cur.execute(
                "SELECT subscription_tier FROM maya_users WHERE email = %s",
                (email,)
            )
            row = cur.fetchone()
            tier = (row[0] if row else "free") or "free"
            result["tier"] = tier

            if tier in ("standard", "premium"):
                return result  # paid — no limits to check

            # Free tier: check trial + daily limit from alex_user_profiles
            cur.execute(
                """
                SELECT created_at, daily_question_count, daily_reset_date
                FROM alex_user_profiles
                WHERE email = %s
                """,
                (email,)
            )
            profile = cur.fetchone()
            if profile:
                created_at, daily_count, reset_date = profile
                # Trial check
                if created_at:
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - created_at
                    if delta.days >= _TRIAL_DAYS:
                        result["trial_expired"] = True
                        return result
                # Daily limit check
                today = date.today()
                if reset_date and reset_date < today:
                    daily_count = 0  # stale — will be reset on save
                if (daily_count or 0) >= _FREE_DAILY_LIMIT:
                    result["daily_limit_reached"] = True
    except Exception as e:
        logger.warning(f"[WebRateLimit] Check failed for {email}: {e}")
    return result


def _increment_web_daily_count(email: str) -> None:
    """Increment daily question count in alex_user_profiles. Reset if new day."""
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL", "")
        today = date.today()
        with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alex_user_profiles (email, daily_question_count, daily_reset_date)
                VALUES (%s, 1, %s)
                ON CONFLICT (email) DO UPDATE
                    SET daily_question_count = CASE
                            WHEN alex_user_profiles.daily_reset_date IS NULL
                              OR alex_user_profiles.daily_reset_date < EXCLUDED.daily_reset_date
                            THEN 1
                            ELSE alex_user_profiles.daily_question_count + 1
                        END,
                        daily_reset_date = EXCLUDED.daily_reset_date
                """,
                (email, today)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[WebRateLimit] Counter update failed for {email}: {e}")

chat_claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PINECONE_AVAILABLE = False
chat_index = None

try:
    from pinecone import Pinecone, ServerlessSpec
    
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if pinecone_key:
        chat_pc = Pinecone(api_key=pinecone_key)
        
        INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
        try:
            chat_index = chat_pc.Index(INDEX_NAME)
            PINECONE_AVAILABLE = True
            logger.info(f"Pinecone connected to index: {INDEX_NAME}")
        except Exception as e:
            logger.warning(f"Pinecone index not found, creating: {e}")
            try:
                chat_pc.create_index(
                    name=INDEX_NAME,
                    dimension=1536,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
                chat_index = chat_pc.Index(INDEX_NAME)
                PINECONE_AVAILABLE = True
            except Exception as create_err:
                logger.error(f"Failed to create Pinecone index: {create_err}")
    else:
        logger.warning("PINECONE_API_KEY not set - RAG features disabled")
except ImportError as e:
    logger.warning(f"Pinecone not installed: {e}")
except Exception as e:
    logger.error(f"Error initializing Pinecone: {e}")

# Ukrainian phone number patterns: +380XXXXXXXXX, 380XXXXXXXXX, 0XXXXXXXXX, (0XX) XXX-XX-XX
_PHONE_RE = re.compile(
    r'(?:'
    r'\+?380\d{9}'                                    # +380XXXXXXXXX or 380XXXXXXXXX
    r'|'
    r'\(0\d{2}\)[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}'  # (0XX) XXX-XX-XX
    r'|'
    r'(?<!\d)0\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)'  # 0XX-XXX-XX-XX
    r')'
)


async def _notify_alex_lead(phone: str, user_email: str, history: list) -> None:
    """Send a HoReCa lead notification via Telegram and optionally email."""
    context_parts = history[-3:] if history else []
    context_text = "\n".join(
        f"{m['role'].title()}: {m['content'][:200]}" for m in context_parts
    ) or "Немає попередніх повідомлень"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # 1. Telegram (primary — works immediately with existing bot token)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        try:
            import httpx
            tg_text = (
                f"🎯 <b>Новий лід від Alex — HoReCa контакт</b>\n\n"
                f"📞 Телефон: <code>{phone}</code>\n"
                f"📧 Email: {user_email or 'невідомо'}\n"
                f"📅 Дата: {now}\n\n"
                f"💬 <b>Контекст розмови:</b>\n{context_text[:800]}"
            )
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": tg_text, "parse_mode": "HTML"},
                    timeout=5.0,
                )
            logger.info(f"Alex lead Telegram notification sent for phone {phone}")
        except Exception as e:
            logger.warning(f"Alex lead Telegram notification failed: {e}")

    # 2. Email via SMTP (requires SMTP_USER + SMTP_PASS env vars)
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    if smtp_user and smtp_pass:
        try:
            body = (
                f"Клієнт зацікавлений у співпраці з AVTD.\n\n"
                f"Телефон: {phone}\n"
                f"Email: {user_email or 'невідомо'}\n"
                f"Контекст розмови:\n{context_text}\n"
                f"Дата: {now}"
            )
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = "Новий лід від Alex — HoReCa контакт"
            msg["From"] = smtp_user
            msg["To"] = "admin@gradusmedia.org"
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info(f"Alex lead email sent for phone {phone}")
        except Exception as e:
            logger.warning(f"Alex lead email failed: {e}")


class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None
    avatar: Optional[str] = None
    source: Optional[str] = "website"  # "telegram" or "website"
    user_email: Optional[str] = None   # for lead capture + memory
    user_tier: Optional[str] = "free"  # "free" | "standard" | "premium"

class ChatResponse(BaseModel):
    response: str
    type: str
    avatar_used: str
    ingestion_data: Optional[dict] = None
    sources_used: Optional[List[str]] = None

@chat_router.post("/")
async def chat_with_avatars(request: ChatRequest):
    """Chat with Gradus AI avatars (Maya/Alex/General)"""

    message = request.message
    history = request.conversation_history or []

    # ── Web-side rate limiting for Alex (free tier) ──────────────────────────
    # Only enforce when email is known and avatar is alex, on website source.
    _detected_avatar = request.avatar or detect_avatar_role(message, history)
    if (
        _detected_avatar == "alex"
        and request.user_email
        and request.source == "website"
    ):
        _limits = _get_web_user_limits(request.user_email)
        if _limits["trial_expired"]:
            raise HTTPException(
                status_code=402,
                detail={
                    "reason": "trial_expired",
                    "message": (
                        "Ваш 7-денний безкоштовний пробний доступ завершився. "
                        "Перейдіть на платний тариф на gradusmedia.org/тарифи"
                    ),
                },
            )
        if _limits["daily_limit_reached"]:
            raise HTTPException(
                status_code=402,
                detail={
                    "reason": "daily_limit",
                    "message": (
                        f"Ви використали {_FREE_DAILY_LIMIT} безкоштовних питань сьогодні. "
                        "Повертайтесь завтра або перейдіть на платний тариф → gradusmedia.org/тарифи"
                    ),
                },
            )
        # Override tier from DB for memory eligibility
        request = request.model_copy(update={"user_tier": _limits["tier"]})

    urls = extract_urls(message)
    
    if urls and is_ingestion_request(message) and PINECONE_AVAILABLE:
        url = urls[0]
        company_name = extract_company_name_from_url(url)
        
        result = await ingest_website(url, company_name, chat_index)
        
        if result['status'] == 'success':
            response_text = f"""{result['message']}

Тепер можу відповідати на питання про {company_name} на основі їхнього сайту.

Що саме вас цікавить?"""
            
            return ChatResponse(
                response=response_text,
                type="ingestion_result",
                avatar_used="general",
                ingestion_data=result
            )
        else:
            return ChatResponse(
                response=f"Вибачте, виникла проблема: {result['message']}",
                type="error",
                avatar_used="general",
                ingestion_data=result
            )
    
    if request.avatar:
        avatar_role = request.avatar
    else:
        avatar_role = detect_avatar_role(message, history)

    # Phone number lead capture — intercept before calling Claude
    if avatar_role == "alex":
        phone_match = _PHONE_RE.search(message)
        if phone_match:
            phone = phone_match.group().strip()
            await _notify_alex_lead(phone, request.user_email, history)
            return ChatResponse(
                response=(
                    "Дякую! Ваш номер передано нашому HoReCa-менеджеру. "
                    "Очікуйте дзвінка протягом 1 робочого дня. "
                    "Якщо є ще питання — я тут!"
                ),
                type="chat",
                avatar_used="alex",
            )

    system_prompt = get_avatar_personality(avatar_role, history_len=len(history))

    # ── Alex memory: inject past context on new session for paid users ──────
    is_paid = request.user_tier in PAID_TIERS
    user_email = request.user_email
    memory_data = None

    if avatar_role == "alex" and is_paid and user_email and len(history) == 0:
        try:
            from models import SessionLocal
            db = SessionLocal()
            try:
                memory_data = load_memory_sync(user_email, db)
                memory_block = format_memory_context(
                    memory_data["messages"], memory_data["business_data"]
                )
                if memory_block:
                    system_prompt += f"\n\n{memory_block}"
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Memory load failed for {user_email}: {e}")
    elif avatar_role == "alex" and not is_paid and user_email:
        logger.info(f"Memory skipped — free tier: {user_email}")

    rag_context = ""
    sources = []
    if PINECONE_AVAILABLE:
        expanded_query = expand_brand_query(message)
        rag_context, sources = await retrieve_context(expanded_query, chat_index)

        if rag_context:
            system_prompt += f"\n\n{rag_context}\n\nIMPORTANT: Use the above information when relevant. Mention sources."

    messages = history.copy()
    messages.append({"role": "user", "content": message})

    try:
        # Model selection: Alex always uses ALEX_CHAT_MODEL; others use channel-based
        if avatar_role == "alex":
            model_to_use = ALEX_CHAT_MODEL
        elif request.source == "telegram":
            model_to_use = CLAUDE_MODEL_TELEGRAM
        else:
            model_to_use = CLAUDE_MODEL_WEBSITE
        logger.info(f"Chat using model {model_to_use} | avatar={avatar_role} | source={request.source}")

        response = chat_claude.messages.create(
            model=model_to_use,
            max_tokens=3000,
            system=system_prompt,
            messages=messages
        )

        assistant_message = response.content[0].text

        from config.agent_personas import validate_gender
        if avatar_role == "maya":
            validate_gender("maya_hr", assistant_message)
        elif avatar_role == "alex":
            validate_gender("alex_gradus", assistant_message)

        # ── Alex memory: save exchange + trigger profile extraction ────────
        if avatar_role == "alex" and is_paid and user_email:
            try:
                from models import SessionLocal
                import os as _os
                db = SessionLocal()
                try:
                    save_exchange_sync(user_email, message, assistant_message, db)
                finally:
                    db.close()

                # Every PROFILE_TRIGGER_EVERY exchanges, extract business profile in background
                exchange_count = (len(history) // 2) + 1
                if exchange_count % PROFILE_TRIGGER_EVERY == 0:
                    all_msgs = list(history) + [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": assistant_message},
                    ]
                    db_url = _os.getenv("NEON_DATABASE_URL") or _os.getenv("DATABASE_URL")
                    asyncio.create_task(
                        extract_and_update_profile(user_email, all_msgs, db_url)
                    )
            except Exception as e:
                logger.warning(f"Memory save failed for {user_email}: {e}")

        # ── Web free-tier counter ───────────────────────────────────────────
        if (
            avatar_role == "alex"
            and not is_paid
            and user_email
            and request.source == "website"
        ):
            _increment_web_daily_count(user_email)

        # ── Telegram nudge (one-time, first response for registered users) ──
        if avatar_role == "alex" and user_email and request.source == "website":
            try:
                import psycopg2 as _pg
                _db_url = os.getenv("DATABASE_URL", "")
                with _pg.connect(_db_url) as _nudge_conn, _nudge_conn.cursor() as _nc:
                    _nc.execute(
                        "SELECT telegram_nudge_sent FROM maya_users WHERE email = %s",
                        (user_email,),
                    )
                    _row = _nc.fetchone()
                    if _row is not None and _row[0] is False:
                        assistant_message += (
                            "\n\n---\n"
                            "💬 До речі — зі мною зручніше у Telegram. "
                            "Там без браузера, просто пишіть будь-коли:\n"
                            "👉 t.me/alexgradus_bot"
                        )
                        _nc.execute(
                            "UPDATE maya_users SET telegram_nudge_sent = TRUE WHERE email = %s",
                            (user_email,),
                        )
                        _nudge_conn.commit()
            except Exception as _ne:
                logger.warning(f"Telegram nudge check failed: {_ne}")

        return ChatResponse(
            response=assistant_message,
            type="chat",
            avatar_used=avatar_role,
            sources_used=sources if sources else None
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {str(e)}"
        )

@chat_router.get("/avatars")
async def list_avatars():
    """List available avatars"""
    return {
        "avatars": ["maya", "alex", "general"],
        "metadata": AVATAR_METADATA
    }

@chat_router.post("/switch-avatar")
async def switch_avatar(avatar: str):
    """Switch to specific avatar"""
    if avatar not in ["maya", "alex", "general"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid avatar. Choose: maya, alex, or general"
        )
    
    return {
        "avatar": avatar,
        "metadata": AVATAR_METADATA[avatar],
        "message": f"Switched to {AVATAR_METADATA[avatar]['name']}"
    }

@chat_router.get("/knowledge-stats")
async def knowledge_stats():
    """Get vector database statistics"""
    if not PINECONE_AVAILABLE:
        return {
            "status": "disabled",
            "message": "Pinecone not configured. Set PINECONE_API_KEY to enable RAG."
        }
    
    try:
        stats = chat_index.describe_index_stats()
        return {
            "total_vectors": stats.total_vector_count,
            "namespaces": dict(stats.namespaces) if stats.namespaces else {},
            "dimension": 1536,
            "index_name": os.getenv("PINECONE_INDEX_NAME", "gradus-media")
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@chat_router.delete("/clear-knowledge")
async def clear_knowledge(confirm: bool = False):
    """Clear vector database (use with caution!)"""
    if not PINECONE_AVAILABLE:
        return {"status": "disabled", "message": "Pinecone not configured"}
    
    if not confirm:
        return {
            "message": "Add ?confirm=true to actually clear the knowledge base"
        }
    
    try:
        chat_index.delete(delete_all=True, namespace="company_knowledge")
        return {
            "status": "success",
            "message": "Knowledge base cleared"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@chat_router.get("/health")
async def chat_health():
    """Health check for chat system"""
    return {
        "status": "healthy",
        "system": "Gradus AI Chat",
        "avatars_available": ["maya", "alex", "general"],
        "features": ["url_detection", "multi_avatar"],
        "rag_enabled": PINECONE_AVAILABLE,
        "pinecone_connected": PINECONE_AVAILABLE,
        "claude_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }
