"""
LinkedIn Daily News Digest Service
-----------------------------------
Fetches top 5 recent HoReCa news items, generates AI-powered LinkedIn insights
via Claude Haiku, posts as a native text post (no link in body),
then immediately posts a first comment containing all the article links.

DB: saves each run to the `linkedin_posts` table (migration 031).
Scheduling: daily at 07:00 UTC (09:00 Kyiv) via scheduler.py.

Environment variables required:
  LINKEDIN_ACCESS_TOKEN   — OAuth 2.0 bearer token (w_organization_social scope)
  LINKEDIN_ORGANIZATION_URN — e.g. "urn:li:organization:123456"
  ANTHROPIC_API_KEY
  DATABASE_URL
"""
import json
import logging
import os
from datetime import datetime, timezone

import anthropic
import psycopg2
import requests

logger = logging.getLogger(__name__)

DB_URL  = os.environ.get("DATABASE_URL", "")
LI_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LI_ORG   = os.environ.get("LINKEDIN_ORGANIZATION_URN", "")
LI_BASE  = "https://api.linkedin.com/v2"

HAIKU_MODEL = "claude-haiku-4-5"


def _get_conn():
    return psycopg2.connect(DB_URL)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Fetch latest news
# ─────────────────────────────────────────────────────────────────────────────

def fetch_latest_news(limit: int = 5) -> list[dict]:
    """
    Pulls the most recently posted approved articles from content_queue.
    Returns list of dicts: id, title, text, source, source_url.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,
                       COALESCE(translated_title, source_title) AS title,
                       COALESCE(translated_text, original_text) AS body,
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

    return [
        {"id": r[0], "title": r[1], "text": r[2], "source": r[3], "url": r[4]}
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Generate LinkedIn insight via Claude Haiku
# ─────────────────────────────────────────────────────────────────────────────

def generate_insight(article: dict) -> str:
    """
    Uses Claude Haiku to condense one article into a 2-3 sentence
    LinkedIn-optimized insight in Ukrainian.
    Returns the insight string (plain text, no markdown).
    """
    client = anthropic.Anthropic()
    title  = article.get("title", "")
    body   = (article.get("text") or "")[:1500]

    prompt = (
        f"Ти — HoReCa-консультант Gradus AI. Напиши 2-3 речення LinkedIn-инсайту "
        f"українською мовою на основі цієї новини. Текст має бути конкретним, корисним "
        f"для рестораторів та власників барів, без загальних фраз. НЕ включай посилання.\n\n"
        f"Заголовок: {title}\n\n"
        f"Текст: {body}"
    )

    try:
        msg = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"[LinkedInDigest] Haiku insight failed: {e}")
        return title


# ─────────────────────────────────────────────────────────────────────────────
# 3. Post to LinkedIn (text only — no link in body)
# ─────────────────────────────────────────────────────────────────────────────

def _li_headers() -> dict:
    return {
        "Authorization": f"Bearer {LI_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def post_text_to_linkedin(post_text: str) -> dict | None:
    """Posts a native LinkedIn text post via ugcPosts. Returns result dict or None on failure."""
    if not LI_TOKEN or not LI_ORG:
        logger.warning("[LinkedInDigest] LINKEDIN_ACCESS_TOKEN or LINKEDIN_ORGANIZATION_URN not set")
        return None

    payload = {
        "author": LI_ORG,
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
        resp = requests.post(f"{LI_BASE}/ugcPosts", headers=_li_headers(), json=payload, timeout=15)
        if resp.status_code == 201:
            post_id = resp.json().get("id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}"
            logger.info(f"[LinkedInDigest] Post published: {post_id}")
            return {"post_id": post_id, "post_url": post_url}
        else:
            logger.error(f"[LinkedInDigest] Post failed ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        logger.error(f"[LinkedInDigest] Post request error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Post first comment with links (avoids algo suppression on main post)
# ─────────────────────────────────────────────────────────────────────────────

def post_first_comment(post_id: str, links_text: str) -> bool:
    """Adds the first comment to a LinkedIn post containing source URLs."""
    if not LI_TOKEN or not LI_ORG:
        return False

    payload = {
        "actor": LI_ORG,
        "message": {"text": links_text},
        "object": post_id,
    }

    try:
        resp = requests.post(
            f"{LI_BASE}/socialActions/{post_id}/comments",
            headers=_li_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.info(f"[LinkedInDigest] First comment added to {post_id}")
            return True
        else:
            logger.warning(f"[LinkedInDigest] Comment failed ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[LinkedInDigest] Comment request error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Save run to linkedin_posts table
# ─────────────────────────────────────────────────────────────────────────────

def save_linkedin_post(post_id: str, post_url: str, snippet: str, article_ids: list[int]) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO linkedin_posts (post_id, post_url, content_snippet, article_ids, posted_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (post_id, post_url, snippet[:500], json.dumps(article_ids)),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[LinkedInDigest] DB save failed: {e}")
        conn.rollback()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def post_daily_digest() -> dict:
    """
    Full pipeline:
      1. Fetch top 5 posted articles
      2. Generate Haiku insights for each
      3. Build LinkedIn post (insights only, no links)
      4. Publish post
      5. Add first comment with source links
      6. Save to linkedin_posts table
    Returns: {"status": "ok"|"skipped"|"error", ...}
    """
    logger.info("[LinkedInDigest] Starting daily digest...")

    articles = fetch_latest_news(limit=5)
    if not articles:
        logger.warning("[LinkedInDigest] No posted articles found — skipping")
        return {"status": "skipped", "reason": "no articles"}

    insights = []
    for art in articles:
        insight = generate_insight(art)
        insights.append({"article": art, "insight": insight})
        logger.info(f"[LinkedInDigest] Insight generated for article {art['id']}")

    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    post_lines = [f"📰 HoReCa дайджест — {today}\n"]
    for i, item in enumerate(insights, 1):
        post_lines.append(f"{i}. {item['insight']}\n")
    post_lines.append(
        "\n🔗 Повні матеріали — у першому коментарі.\n"
        "#HoReCa #Бар #Ресторан #AlexGradus #GradusMedia"
    )
    post_text = "\n".join(post_lines)

    result = post_text_to_linkedin(post_text)
    if not result:
        return {"status": "error", "reason": "LinkedIn API failed"}

    post_id  = result["post_id"]
    post_url = result["post_url"]

    links_lines = ["📎 Джерела:\n"]
    for i, item in enumerate(insights, 1):
        url = item["article"].get("url") or ""
        title = item["article"].get("title", f"Стаття {i}")
        if url:
            links_lines.append(f"{i}. {title}\n{url}")
    links_lines.append("\n🌐 gradus-ai.onrender.com")
    comment_text = "\n".join(links_lines)

    post_first_comment(post_id, comment_text)

    article_ids = [item["article"]["id"] for item in insights]
    save_linkedin_post(post_id, post_url, post_text[:500], article_ids)

    logger.info(f"[LinkedInDigest] Done. post_id={post_id} articles={article_ids}")
    return {"status": "ok", "post_id": post_id, "post_url": post_url, "articles": len(articles)}
