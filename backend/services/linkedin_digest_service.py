"""
LinkedIn Daily News Digest Service
-----------------------------------
Fetches the 5 most recent posted HoReCa articles from DB, generates a single
150-200 word Ukrainian LinkedIn post via Claude Sonnet (high-quality copywriting),
publishes it as native text (no link in body), then immediately:
  1. Adds first comment: "🔗 gradusmedia.org"
  2. Sends Telegram notification to HORECA_TG_GROUP_ID

DB: saves each run to the `linkedin_posts` table (migration 031/032).
Scheduling: daily at 07:00 UTC (09:00 Kyiv) via scheduler.py.

Environment variables required:
  LINKEDIN_ACCESS_TOKEN   — personal OAuth 2.0 bearer token (w_member_social scope)
                            TOKEN EXPIRES: ~June 6 2026 (60 days from April 7 2026)
                            Regenerate at: linkedin.com/developers/tools/oauth/token-generator
  LINKEDIN_AUTHOR_URN     — e.g. "urn:li:person:_Ysk9NLaBQ"
  HORECA_TG_GROUP_ID      — Telegram group ID for post notifications
  TELEGRAM_BOT_TOKEN      — bot token used for Telegram notification
  ANTHROPIC_API_KEY
  DATABASE_URL
"""
import json
import logging
import os

import anthropic
import psycopg2
import requests

logger = logging.getLogger(__name__)

DB_URL      = os.environ.get("DATABASE_URL", "")
LI_BASE     = "https://api.linkedin.com/v2"

SONNET_MODEL = "claude-sonnet-4-20250514"


def _li_token() -> str:
    return os.environ.get("LINKEDIN_ACCESS_TOKEN", "")


def _li_author() -> str:
    return os.environ.get("LINKEDIN_AUTHOR_URN", "")


def _get_conn():
    return psycopg2.connect(DB_URL)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Fetch latest news
# ─────────────────────────────────────────────────────────────────────────────

def _get_used_article_ids(conn, days: int = 30) -> set[int]:
    """
    Returns the set of content_queue article IDs already used in LinkedIn
    posts within the last `days` days. Reads the JSONB article_ids column.
    """
    used: set[int] = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT article_ids
                FROM linkedin_posts
                WHERE posted_at >= NOW() - (%s * INTERVAL '1 day')
                  AND article_ids IS NOT NULL
                """,
                (days,)
            )
            for (ids_json,) in cur.fetchall():
                if isinstance(ids_json, list):
                    used.update(int(i) for i in ids_json)
    except Exception as e:
        logger.warning(f"[LinkedInDigest] Could not fetch used article IDs: {e}")
    return used


def fetch_latest_news(limit: int = 5) -> list[dict]:
    """
    Pulls the most recently posted approved articles from content_queue,
    excluding any article IDs already used in a LinkedIn post in the last
    30 days to prevent duplicate content.

    If fewer than `limit` fresh articles are available, uses what's there
    and logs a warning — never skips the post entirely.
    """
    conn = _get_conn()
    try:
        used_ids = _get_used_article_ids(conn, days=30)

        with conn.cursor() as cur:
            if used_ids:
                cur.execute(
                    """
                    SELECT id,
                           COALESCE(translated_title, source_title) AS title,
                           COALESCE(translated_text, original_text)  AS body,
                           source,
                           source_url
                    FROM content_queue
                    WHERE status = 'posted'
                      AND COALESCE(translated_title, source_title) IS NOT NULL
                      AND id != ALL(%s)
                    ORDER BY posted_at DESC NULLS LAST, created_at DESC
                    LIMIT %s
                    """,
                    (list(used_ids), limit)
                )
            else:
                cur.execute(
                    """
                    SELECT id,
                           COALESCE(translated_title, source_title) AS title,
                           COALESCE(translated_text, original_text)  AS body,
                           source,
                           source_url
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

    articles = [
        {"id": r[0], "title": r[1], "text": r[2], "source": r[3], "url": r[4]}
        for r in rows
    ]

    if len(articles) < limit:
        logger.warning(
            f"[LinkedInDigest] Only {len(articles)} fresh articles available "
            f"(wanted {limit}, {len(used_ids)} excluded as used in last 30 days) — "
            "proceeding with available content"
        )
    else:
        logger.info(
            f"[LinkedInDigest] Fetched {len(articles)} fresh articles "
            f"({len(used_ids)} excluded as used in last 30 days)"
        )

    return articles


# ─────────────────────────────────────────────────────────────────────────────
# 2. Generate full LinkedIn post via Claude Sonnet
# ─────────────────────────────────────────────────────────────────────────────

def generate_linkedin_post(articles: list[dict]) -> str:
    """
    Uses Claude Sonnet to write a single 150-200 word Ukrainian LinkedIn post
    covering the top HoReCa news. Professional tone, no markdown, ends with
    the fixed CTA line. No URLs in the body.
    """
    client = anthropic.Anthropic()

    news_block = "\n\n".join(
        f"[{i}] {a['title']}\n{(a.get('text') or '')[:600]}"
        for i, a in enumerate(articles, 1)
    )

    prompt = (
        "Ти — контент-менеджер GradusMedia, медіа для Ukrainian HoReCa-ринку. "
        "Напиши один LinkedIn-пост українською мовою (150-200 слів).\n\n"
        "Вимоги:\n"
        "- Профіл читача: ресторатори, власники барів, F&B-менеджери, дистриб'ютори\n"
        "- Тон: фаховий, конкретний, без кліше та загальних фраз\n"
        "- Структура: короткий гачок (1-2 речення) → 2-3 ключових інсайти з новин → заклик до дії\n"
        "- Можна використати 1-2 emoji якщо доречно, але не перевантажувати\n"
        "- НЕ включай посилань та URL\n"
        "- НЕ використовуй markdown (зірочки, решітки тощо)\n"
        "- Останній рядок ЗАВЖДИ: \"Детальніше на gradusmedia.org?utm_source=linkedin&utm_medium=social&utm_campaign=weekly_digest 👇\"\n"
        "- Після тексту постав хештеги у новому рядку: #HoReCa #Бар #Ресторан #GradusMedia\n\n"
        f"Новини для опрацювання:\n\n{news_block}"
    )

    try:
        msg = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"[LinkedInDigest] Sonnet post generation failed: {e}")
        titles = " | ".join(a["title"] for a in articles[:3])
        return (
            f"HoReCa дайджест тижня:\n\n{titles}\n\n"
            "Детальніше на gradusmedia.org?utm_source=linkedin&utm_medium=social&utm_campaign=weekly_digest 👇\n"
            "#HoReCa #Бар #Ресторан #GradusMedia"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Post to LinkedIn (text only — no link in body)
# ─────────────────────────────────────────────────────────────────────────────

def _li_headers() -> dict:
    return {
        "Authorization": f"Bearer {_li_token()}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def post_text_to_linkedin(post_text: str) -> dict | None:
    """
    Posts a native LinkedIn text post via ugcPosts using personal profile URN.
    Returns {"post_id": ..., "post_url": ...} or None on failure.
    """
    token  = _li_token()
    author = _li_author()

    if not token:
        logger.warning(
            "[LinkedInDigest] LINKEDIN_ACCESS_TOKEN not set — skipping post"
        )
        return None
    if not author:
        logger.warning(
            "[LinkedInDigest] LINKEDIN_AUTHOR_URN not set — skipping post"
        )
        return None

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    try:
        resp = requests.post(
            f"{LI_BASE}/ugcPosts",
            headers=_li_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code == 201:
            post_id  = resp.json().get("id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}"
            logger.info(f"[LinkedInDigest] Post published: {post_id}")
            return {"post_id": post_id, "post_url": post_url}
        elif resp.status_code == 401:
            logger.error(
                "[LinkedInDigest] 401 Unauthorized — LinkedIn token expired. "
                # TOKEN EXPIRES: ~June 6 2026 (60 days from April 7 2026)
                "Regenerate at: linkedin.com/developers/tools/oauth/token-generator"
            )
            return None
        else:
            logger.error(
                f"[LinkedInDigest] Post failed ({resp.status_code}): {resp.text[:300]}"
            )
            return None
    except Exception as e:
        logger.error(f"[LinkedInDigest] Post request error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Post first comment: "🔗 gradusmedia.org"
# ─────────────────────────────────────────────────────────────────────────────

def post_first_comment(post_id: str) -> str | None:
    """
    Adds the first comment to a LinkedIn post.
    Returns the comment_id string on success, None on failure.
    """
    author = _li_author()
    if not _li_token() or not author:
        return None

    payload = {
        "actor":   author,
        "message": {"text": "🔗 gradusmedia.org?utm_source=linkedin&utm_medium=social&utm_campaign=weekly_digest"},
        "object":  post_id,
    }

    try:
        resp = requests.post(
            f"{LI_BASE}/socialActions/{post_id}/comments",
            headers=_li_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            comment_id = resp.json().get("id", "")
            logger.info(f"[LinkedInDigest] First comment added: {comment_id}")
            return comment_id or "ok"
        else:
            logger.warning(
                f"[LinkedInDigest] Comment failed ({resp.status_code}): {resp.text[:200]}"
            )
            return None
    except Exception as e:
        logger.error(f"[LinkedInDigest] Comment request error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Telegram notification to HoReCa group
# ─────────────────────────────────────────────────────────────────────────────

def send_tg_notification(post_url: str) -> bool:
    """
    Sends a Telegram message to HORECA_TG_GROUP_ID with the LinkedIn post URL.
    Returns True on success.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    group_id  = os.environ.get("HORECA_TG_GROUP_ID", "")

    if not bot_token or not group_id:
        logger.warning(
            "[LinkedInDigest] TELEGRAM_BOT_TOKEN or HORECA_TG_GROUP_ID not set — "
            "skipping Telegram notification"
        )
        return False

    text = (
        "📢 Новий пост на LinkedIn GradusMedia\n"
        f"{post_url}\n"
        "Поділіться з вашою мережею — це займе 10 секунд 👆"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": group_id, "text": text, "disable_web_page_preview": False},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"[LinkedInDigest] Telegram notification sent to {group_id}")
            return True
        else:
            logger.warning(
                f"[LinkedInDigest] Telegram notification failed ({resp.status_code}): "
                f"{resp.text[:200]}"
            )
            return False
    except Exception as e:
        logger.error(f"[LinkedInDigest] Telegram notification error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 6. Save run to linkedin_posts table
# ─────────────────────────────────────────────────────────────────────────────

def save_linkedin_post(
    post_id: str,
    post_url: str,
    snippet: str,
    article_ids: list[int],
    comment_id: str | None,
    tg_sent: bool,
) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO linkedin_posts
                    (post_id, post_url, content_snippet, article_ids,
                     comment_id, tg_notification_sent, posted_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    post_id,
                    post_url,
                    snippet[:500],
                    json.dumps(article_ids),
                    comment_id,
                    tg_sent,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[LinkedInDigest] DB save failed: {e}")
        conn.rollback()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def post_daily_digest() -> dict:
    """
    Full pipeline:
      1. Fetch top 5 posted articles from DB
      2. Generate a 150-200 word Ukrainian LinkedIn post via Claude Sonnet
      3. Publish post (text only, no link)
      4. Post first comment: "🔗 gradusmedia.org"
      5. Send Telegram notification to HORECA_TG_GROUP_ID
      6. Save result to linkedin_posts table
    Returns: {"status": "ok"|"skipped"|"error", ...}
    """
    logger.info("[LinkedInDigest] Starting daily digest...")

    articles = fetch_latest_news(limit=5)
    if not articles:
        logger.warning("[LinkedInDigest] No posted articles found — skipping")
        return {"status": "skipped", "reason": "no articles"}

    logger.info(f"[LinkedInDigest] Generating Sonnet post from {len(articles)} articles...")
    post_text = generate_linkedin_post(articles)
    logger.info(f"[LinkedInDigest] Post text ({len(post_text.split())} words) ready")

    result = post_text_to_linkedin(post_text)
    if not result:
        return {"status": "error", "reason": "LinkedIn API failed"}

    post_id  = result["post_id"]
    post_url = result["post_url"]

    comment_id = post_first_comment(post_id)
    tg_sent    = send_tg_notification(post_url)

    article_ids = [a["id"] for a in articles]
    save_linkedin_post(post_id, post_url, post_text, article_ids, comment_id, tg_sent)

    logger.info(
        f"[LinkedInDigest] Done — post_id={post_id} "
        f"comment={'ok' if comment_id else 'failed'} "
        f"tg={'ok' if tg_sent else 'skipped'} "
        f"articles={article_ids}"
    )
    return {
        "status":     "ok",
        "post_id":    post_id,
        "post_url":   post_url,
        "comment_id": comment_id,
        "tg_sent":    tg_sent,
        "articles":   len(articles),
    }
