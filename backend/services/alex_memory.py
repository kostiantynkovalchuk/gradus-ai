"""
Alex Gradus per-user conversation memory.
Paid users (standard + premium) get persistent memory across sessions.
Free users always start fresh.
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAID_TIERS = {"standard", "premium"}
MEMORY_LIMIT = 10
PROFILE_TRIGGER_EVERY = 3


# ─── Read ────────────────────────────────────────────────────────────────────

def load_memory_sync(email: str, db: Session) -> dict:
    """
    Load last MEMORY_LIMIT messages + business profile for a paid user.
    Returns {"messages": [...], "business_data": {...}, "has_profile": bool}
    """
    rows = db.execute(text("""
        SELECT role, content, created_at
        FROM alex_conversations
        WHERE email = :email
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"email": email, "lim": MEMORY_LIMIT}).fetchall()

    messages = [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    profile_row = db.execute(text("""
        SELECT business_data FROM alex_user_profiles WHERE email = :email
    """), {"email": email}).fetchone()

    business_data = profile_row[0] if profile_row else {}
    has_profile = bool(business_data)

    logger.info(
        f"Memory loaded for {email}: {len(messages)} messages, "
        f"profile: {'yes' if has_profile else 'no'}"
    )
    return {"messages": messages, "business_data": business_data, "has_profile": has_profile}


def format_memory_context(messages: list, business_data: dict) -> str:
    """Format memory into a system-prompt block."""
    if not messages and not business_data:
        return ""

    parts = ["═══ ПАМ'ЯТЬ ПРО КЛІЄНТА ═══"]

    if business_data:
        clean = {k: v for k, v in business_data.items() if v not in (None, [], "")}
        if clean:
            parts.append("Бізнес-профіль клієнта:")
            for k, v in clean.items():
                parts.append(f"  {k}: {v}")

    if messages:
        parts.append("\nОстання розмова:")
        for m in messages:
            label = "Клієнт" if m["role"] == "user" else "Alex"
            parts.append(f"  {label}: {m['content'][:300]}")

    parts.append(
        "\n═══════════════════════════\n"
        "Використовуй цю інформацію природньо — не згадуй, що ти 'пам'ятаєш' "
        "з попередніх сесій, просто веди розмову як продовження."
    )
    return "\n".join(parts)


# ─── Write ───────────────────────────────────────────────────────────────────

def save_exchange_sync(email: str, user_msg: str, assistant_msg: str, db: Session) -> None:
    """Save one user+assistant exchange to alex_conversations."""
    db.execute(text("""
        INSERT INTO alex_conversations (email, role, content)
        VALUES (:email, 'user', :content)
    """), {"email": email, "content": user_msg})
    db.execute(text("""
        INSERT INTO alex_conversations (email, role, content)
        VALUES (:email, 'assistant', :content)
    """), {"email": email, "content": assistant_msg})
    db.commit()


# ─── Background profile extraction ───────────────────────────────────────────

EXTRACTION_PROMPT = """Проаналізуй розмову нижче та витягни бізнес-факти про заклад клієнта.

Розмова:
{conversation}

Поточний профіль:
{current_profile}

Поверни ТІЛЬКИ JSON з оновленими даними (додай нові факти, не видаляй існуючі):
{{
  "format": "бар/ресторан/кафе/готель/...",
  "avg_check_uah": null,
  "target_audience": null,
  "location_city": null,
  "staff_bartenders": null,
  "current_suppliers": [],
  "menu_update_frequency": null,
  "beverage_revenue_pct": null,
  "top_selling_categories": [],
  "business_goals": [],
  "pain_points": [],
  "notes": null
}}

Якщо факт невідомий — залиш null. Поверни ТІЛЬКИ JSON, без пояснень."""


async def extract_and_update_profile(
    email: str,
    recent_messages: list,
    db_url: str,
) -> None:
    """
    Background task: extract business facts from recent messages using Haiku,
    then merge into alex_user_profiles using jsonb || operator.
    """
    try:
        from anthropic import Anthropic
        import os
        from config.models import ALEX_EXTRACTION_MODEL
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(db_url, pool_pre_ping=True)
        DBSession = sessionmaker(bind=engine)
        db = DBSession()

        try:
            profile_row = db.execute(text("""
                SELECT business_data FROM alex_user_profiles WHERE email = :email
            """), {"email": email}).fetchone()
            current_profile = profile_row[0] if profile_row else {}

            conversation_text = "\n".join(
                f"{'Клієнт' if m['role'] == 'user' else 'Alex'}: {m['content']}"
                for m in recent_messages[-6:]
            )

            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=ALEX_EXTRACTION_MODEL,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(
                        conversation=conversation_text,
                        current_profile=json.dumps(current_profile, ensure_ascii=False, indent=2)
                    )
                }]
            )

            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            new_facts = json.loads(raw.strip())

            clean_facts = {k: v for k, v in new_facts.items() if v not in (None, [], "")}
            if not clean_facts:
                return

            db.execute(text("""
                INSERT INTO alex_user_profiles (email, business_data, updated_at)
                VALUES (:email, :data, NOW())
                ON CONFLICT (email) DO UPDATE
                SET business_data = alex_user_profiles.business_data || :data,
                    updated_at = NOW()
            """), {"email": email, "data": json.dumps(clean_facts)})
            db.commit()

            logger.info(f"Profile updated for {email}: {len(clean_facts)} facts extracted")
        finally:
            db.close()
            engine.dispose()

    except Exception as e:
        logger.warning(f"Profile extraction failed for {email}: {e}")


# ─── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup_old_conversations_sync(db: Session) -> int:
    """Keep only the last 50 messages per user. Returns number of rows deleted."""
    result = db.execute(text("""
        DELETE FROM alex_conversations
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at DESC) AS rn
                FROM alex_conversations
            ) ranked
            WHERE rn <= 50
        )
    """))
    db.commit()
    deleted = result.rowcount
    if deleted:
        logger.info(f"Memory cleanup: deleted {deleted} old conversation rows")
    return deleted
