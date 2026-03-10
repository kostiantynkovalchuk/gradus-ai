from fastapi import APIRouter, Request, HTTPException
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

_photo_app = None
_initialized = False


async def get_photo_app():
    global _photo_app, _initialized
    if _photo_app is None:
        token = os.environ.get("PHOTO_REPORT_BOT_TOKEN")
        if not token:
            raise HTTPException(status_code=503, detail="PHOTO_REPORT_BOT_TOKEN not configured")
        from photo_report.bot import create_photo_report_app
        _photo_app = create_photo_report_app()
        if not _initialized:
            await _photo_app.initialize()
            _initialized = True
    return _photo_app


@router.post("/webhook/photo-report")
async def photo_report_webhook(request: Request):
    try:
        from telegram import Update
        app = await get_photo_app()
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Photo report webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/webhook/photo-report/health")
async def photo_report_health():
    token_set = bool(os.environ.get("PHOTO_REPORT_BOT_TOKEN"))
    return {"status": "ok", "service": "photo-report", "token_configured": token_set}
