"""
Alex Avatar Video Digest Pipeline — SCAFFOLD
---------------------------------------------
Generates a weekly AI video digest with Alex Gradus avatar reading
the top 5 HoReCa news stories, distributed to Facebook, Telegram, and LinkedIn.

Status: SCAFFOLD — activate once API keys are provided:
  HEYGEN_API_KEY, HEYGEN_AVATAR_ID, FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN

DB table: video_digests (migration 031)
Schedule: Monday 08:00 UTC (10:00 Kyiv) via scheduler.py

Step flow:
  1. fetch_news_for_script()   — top 5 HoReCa news from DB
  2. generate_alex_script()    — Claude Sonnet → 60-90s spoken Ukrainian script
  3. generate_video_heygen()   — HeyGen /v2/video/generate → video_url
  4. distribute_video()        — parallel: Facebook + Telegram + LinkedIn
  5. update_digest_status()    — save status to video_digests table
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import anthropic
import psycopg2
import requests

logger = logging.getLogger(__name__)

# TODO: HoReCa Staff Search — blocked on Robota.ua CV fetch fix (see Maya Hunt architecture docs)

DB_URL              = os.environ.get("DATABASE_URL", "")
HEYGEN_API_KEY      = os.environ.get("HEYGEN_API_KEY", "")
HEYGEN_AVATAR_ID    = os.environ.get("HEYGEN_AVATAR_ID", "")
FACEBOOK_PAGE_ID    = os.environ.get("FACEBOOK_PAGE_ID", "")
FACEBOOK_TOKEN      = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_MAYA_BOT_TOKEN", "")
LI_TOKEN            = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LI_ORG              = os.environ.get("LINKEDIN_ORGANIZATION_URN", "")

SONNET_MODEL = "claude-sonnet-4-5"


def _get_conn():
    return psycopg2.connect(DB_URL)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Fetch news for script
# ─────────────────────────────────────────────────────────────────────────────

def fetch_news_for_script(limit: int = 5) -> list[dict]:
    """Returns top N recently posted articles for script generation."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,
                       COALESCE(translated_title, source_title) AS title,
                       COALESCE(translated_text, original_text) AS body,
                       source
                FROM content_queue
                WHERE status = 'posted'
                  AND COALESCE(translated_title, source_title) IS NOT NULL
                ORDER BY posted_at DESC NULLS LAST, created_at DESC
                LIMIT %s
                """,
                (limit,)
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [{"id": r[0], "title": r[1], "body": (r[2] or "")[:800], "source": r[3]} for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Generate Alex Gradus script via Claude Sonnet
# ─────────────────────────────────────────────────────────────────────────────

def generate_alex_script(articles: list[dict]) -> str:
    """
    Claude Sonnet generates a 60-90 second spoken Ukrainian script
    in Alex Gradus persona, covering 5 HoReCa stories conversationally.
    """
    client = anthropic.Anthropic()

    stories_block = "\n\n".join(
        f"[{i}] {art['title']}\n{art['body'][:400]}"
        for i, art in enumerate(articles, 1)
    )
    today = datetime.now(timezone.utc).strftime("%d %B %Y")

    prompt = (
        f"Ти — Alex Gradus, досвідчений HoReCa-консультант. Напиши усний сценарій на українській мові "
        f"тривалістю 60-90 секунд для відео-дайджесту новин. Дата: {today}.\n\n"
        f"Стиль: впевнений, конкретний, без зайвих слів, орієнтований на рестораторів і бармени. "
        f"Охопи всі 5 новин органічно, не як список, а як звязну розповідь.\n\n"
        f"Починай з: 'Привіт, я Alex Gradus...' Завершуй закликом: 'До нових зустрічей — і нових прибутків.'\n\n"
        f"Новини тижня:\n{stories_block}"
    )

    try:
        msg = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        script = msg.content[0].text.strip()
        logger.info(f"[VideoDigest] Script generated: {len(script)} chars")
        return script
    except Exception as e:
        logger.error(f"[VideoDigest] Script generation failed: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Generate avatar video via HeyGen
# ─────────────────────────────────────────────────────────────────────────────

def generate_video_heygen(script: str, digest_id: int) -> str | None:
    """
    Submits script to HeyGen /v2/video/generate and polls until done.
    Returns video_url (CDN link) or None on failure.

    Requires:
      HEYGEN_API_KEY   — HeyGen API key
      HEYGEN_AVATAR_ID — Alex avatar ID in HeyGen

    HeyGen docs: https://docs.heygen.com/reference/video-generation
    """
    if not HEYGEN_API_KEY or not HEYGEN_AVATAR_ID:
        logger.warning("[VideoDigest] HEYGEN_API_KEY or HEYGEN_AVATAR_ID not set — skipping video generation")
        return None

    headers = {
        "X-Api-Key": HEYGEN_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": HEYGEN_AVATAR_ID,
                "avatar_style": "normal",
            },
            "voice": {
                "type": "text",
                "input_text": script,
                "voice_id": os.environ.get("HEYGEN_VOICE_ID", ""),
            },
        }],
        "dimension": {"width": 1080, "height": 1920},
        "aspect_ratio": None,
        "test": False,
    }

    try:
        resp = requests.post(
            "https://api.heygen.com/v2/video/generate",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        video_id = data["data"]["video_id"]
        logger.info(f"[VideoDigest] HeyGen job submitted: {video_id}")
    except Exception as e:
        logger.error(f"[VideoDigest] HeyGen submit failed: {e}")
        return None

    for attempt in range(60):
        time.sleep(10)
        try:
            status_resp = requests.get(
                f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                headers=headers,
                timeout=10,
            )
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status")
            if status == "completed":
                video_url = status_data.get("video_url")
                logger.info(f"[VideoDigest] Video ready: {video_url}")
                return video_url
            elif status == "failed":
                logger.error(f"[VideoDigest] HeyGen failed: {status_data}")
                return None
            logger.debug(f"[VideoDigest] Polling attempt {attempt + 1}: {status}")
        except Exception as e:
            logger.warning(f"[VideoDigest] Poll error: {e}")

    logger.error("[VideoDigest] HeyGen timed out after 10 minutes")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Distribute video to all platforms
# ─────────────────────────────────────────────────────────────────────────────

def _post_facebook_video(video_url: str, caption: str) -> bool:
    """Posts video to Facebook Page via Graph API."""
    if not FACEBOOK_PAGE_ID or not FACEBOOK_TOKEN:
        logger.warning("[VideoDigest] Facebook credentials not set")
        return False
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/videos",
            data={
                "file_url": video_url,
                "description": caption,
                "access_token": FACEBOOK_TOKEN,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info(f"[VideoDigest] Facebook posted: {resp.json().get('id')}")
            return True
        else:
            logger.error(f"[VideoDigest] Facebook error ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[VideoDigest] Facebook request failed: {e}")
        return False


def _post_telegram_video(video_url: str, caption: str) -> bool:
    """Sends video to Telegram channel."""
    if not TELEGRAM_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
        logger.warning("[VideoDigest] Telegram channel credentials not set")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "video": video_url,
                "caption": caption,
                "parse_mode": "Markdown",
            },
            timeout=30,
        )
        if resp.ok:
            logger.info("[VideoDigest] Telegram posted")
            return True
        else:
            logger.error(f"[VideoDigest] Telegram error: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[VideoDigest] Telegram request failed: {e}")
        return False


def _post_linkedin_video(video_url: str, caption: str) -> bool:
    """
    Posts video natively to LinkedIn org page,
    then adds first comment with gradusmedia.org link.
    """
    if not LI_TOKEN or not LI_ORG:
        logger.warning("[VideoDigest] LinkedIn credentials not set")
        return False

    headers = {
        "Authorization": f"Bearer {LI_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    payload = {
        "author": LI_ORG,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": caption},
                "shareMediaCategory": "VIDEO",
                "media": [{
                    "status": "READY",
                    "originalUrl": video_url,
                }],
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }
    try:
        resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload, timeout=20)
        if resp.status_code == 201:
            post_id = resp.json().get("id", "")
            logger.info(f"[VideoDigest] LinkedIn posted: {post_id}")
            # First comment with link
            requests.post(
                f"https://api.linkedin.com/v2/socialActions/{post_id}/comments",
                headers=headers,
                json={"actor": LI_ORG, "message": {"text": "🌐 gradus-ai.onrender.com"}, "object": post_id},
                timeout=10,
            )
            return True
        else:
            logger.error(f"[VideoDigest] LinkedIn error ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[VideoDigest] LinkedIn request failed: {e}")
        return False


def distribute_video(video_url: str, script: str, digest_id: int) -> dict:
    """
    Posts video to all three platforms in sequence.
    Each platform failure is independent — others still attempt.
    Returns per-platform status dict.
    """
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    caption = (
        f"🎬 HoReCa відео-дайджест від Alex Gradus — {today}\n\n"
        "Топ новини тижня для рестораторів та барменів 🇺🇦\n"
        "#HoReCa #AlexGradus #GradusMedia"
    )

    results = {
        "facebook":  _post_facebook_video(video_url, caption),
        "telegram":  _post_telegram_video(video_url, caption),
        "linkedin":  _post_linkedin_video(video_url, caption),
    }
    logger.info(f"[VideoDigest] Distribution results: {results}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — DB status tracking
# ─────────────────────────────────────────────────────────────────────────────

def create_digest_record() -> int:
    """Inserts a new video_digests row and returns its id."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO video_digests (status) VALUES ('pending') RETURNING id"
            )
            digest_id = cur.fetchone()[0]
            conn.commit()
            return digest_id
    finally:
        conn.close()


def update_digest_status(
    digest_id: int,
    status: str,
    script: str | None = None,
    video_url: str | None = None,
    distribution: dict | None = None,
) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE video_digests
                SET status              = %s,
                    script              = COALESCE(%s, script),
                    video_url           = COALESCE(%s, video_url),
                    posted_facebook_at  = CASE WHEN %s = true THEN NOW() ELSE posted_facebook_at END,
                    posted_telegram_at  = CASE WHEN %s = true THEN NOW() ELSE posted_telegram_at END,
                    posted_linkedin_at  = CASE WHEN %s = true THEN NOW() ELSE posted_linkedin_at END
                WHERE id = %s
                """,
                (
                    status,
                    script,
                    video_url,
                    distribution.get("facebook") if distribution else False,
                    distribution.get("telegram") if distribution else False,
                    distribution.get("linkedin") if distribution else False,
                    digest_id,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[VideoDigest] update_digest_status failed: {e}")
        conn.rollback()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_weekly_digest() -> dict:
    """
    Full video digest pipeline.
    Safe to call manually for testing; idempotent per run (new DB row each time).
    """
    logger.info("[VideoDigest] === Weekly digest starting ===")
    digest_id = create_digest_record()

    try:
        articles = fetch_news_for_script(limit=5)
        if not articles:
            update_digest_status(digest_id, "failed")
            return {"status": "skipped", "reason": "no articles"}

        update_digest_status(digest_id, "generating")

        script = generate_alex_script(articles)
        update_digest_status(digest_id, "generating", script=script)

        video_url = generate_video_heygen(script, digest_id)
        if not video_url:
            update_digest_status(digest_id, "failed", script=script)
            return {"status": "error", "reason": "video generation failed"}

        update_digest_status(digest_id, "distributing", video_url=video_url)

        dist_results = distribute_video(video_url, script, digest_id)
        final_status = "posted" if any(dist_results.values()) else "failed"
        update_digest_status(digest_id, final_status, distribution=dist_results)

        logger.info(f"[VideoDigest] === Done. status={final_status} id={digest_id} ===")
        return {"status": final_status, "digest_id": digest_id, "distribution": dist_results}

    except Exception as e:
        logger.error(f"[VideoDigest] Unexpected error: {e}", exc_info=True)
        update_digest_status(digest_id, "failed")
        return {"status": "error", "reason": str(e)}
