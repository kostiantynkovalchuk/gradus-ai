"""
TEST 2 — Single broadcast + scoreboard (developer-only).
Sends survey to Konstantin only. Natalia is NOT contacted during test runs.

Usage:
  cd /home/runner/workspace && python backend/scripts/test_survey_send.py
"""
import asyncio
import json
import os
import sys

import httpx
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN  = os.environ.get("TELEGRAM_MAYA_BOT_TOKEN", "")
DB_URL = os.environ.get("DATABASE_URL", "")


async def get_developer_tg_id() -> int:
    """Fetch Konstantin's telegram_id only — developer role."""
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        SELECT telegram_id, full_name FROM hr_users
        WHERE access_level = 'developer'
        AND telegram_id IS NOT NULL
        AND is_active = true
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise ValueError("No developer user found in hr_users")
    print(f"Test recipient: {row[1]} (telegram_id: {row[0]})")
    return row[0]


async def send_test_survey(tg_id: int):
    """Send survey message with inline keyboard to one user."""
    payload = {
        "chat_id": tg_id,
        "text": (
            "🧪 *[ТЕСТ] Опитування*\n\n"
            "У зв'язку з діючими обмеженнями на державні свята під час "
            "воєнного стану просимо поділитись думкою:\n\n"
            "*Чи необхідний Вам вихідний (пн 13/04/26) після Великодня?*"
        ),
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Так", "callback_data": "survey_easter_holiday_2026_yes"},
                {"text": "❌ Ні",  "callback_data": "survey_easter_holiday_2026_no"},
            ]]
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json=payload,
        )
    result = resp.json()
    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        print(f"✅ Survey message sent. message_id: {msg_id}")
        return msg_id
    else:
        print(f"❌ Send failed: {result}")
        return None


async def _build_scoreboard_text(survey_id: str) -> str:
    from services.survey_service import _build_scoreboard_text as _bst
    return await _bst(survey_id)


async def test_post_scoreboard():
    """Post scoreboard to Konstantin only for test."""
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        SELECT telegram_id FROM hr_users
        WHERE access_level = 'developer'
        AND telegram_id IS NOT NULL
        AND is_active = true
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        print("❌ Developer user not found")
        return False

    tg_id = row[0]
    text  = await _build_scoreboard_text("easter_holiday_2026")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": tg_id,
                "text": text,
                "parse_mode": "Markdown",
            },
        )
    result = resp.json()
    if not result.get("ok"):
        print(f"❌ Scoreboard send failed: {result}")
        return False

    msg_id = result["result"]["message_id"]

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO hr_survey_meta (survey_id, scoreboard_targets)
        VALUES (%s, %s)
        ON CONFLICT (survey_id) DO UPDATE
        SET scoreboard_targets = EXCLUDED.scoreboard_targets
    """, (
        "easter_holiday_2026",
        json.dumps([{"chat_id": tg_id, "msg_id": msg_id}]),
    ))
    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Scoreboard sent to Konstantin only. msg_id: {msg_id}")
    return True


async def main():
    print("=" * 50)
    print("TEST 2 — Single broadcast + scoreboard (developer only)")
    print("=" * 50)

    tg_id = await get_developer_tg_id()
    msg_id = await send_test_survey(tg_id)

    if not msg_id:
        print("❌ TEST 2 FAILED at send step. Stopping.")
        return False

    print("\nWaiting 3 seconds before posting scoreboard...")
    await asyncio.sleep(3)

    scoreboard_ok = await test_post_scoreboard()

    print("\n" + "=" * 50)
    if scoreboard_ok:
        print("✅ TEST 2 PASSED")
        print("""
┌─────────────────────────────────────────────────┐
│  MANUAL CHECK REQUIRED — Open Telegram now      │
├─────────────────────────────────────────────────┤
│  Konstantin's phone only:                       │
│  □ Survey message received from Maya HR bot     │
│  □ "[ТЕСТ]" prefix visible in message           │
│  □ Two buttons visible: ✅ Так  and  ❌ Ні      │
│  □ Scoreboard message received separately       │
│  □ Scoreboard shows 0 з 0 проголосували        │
│                                                 │
│  Natalia is NOT contacted during this test.     │
└─────────────────────────────────────────────────┘
""")
    else:
        print("❌ TEST 2 FAILED — fix scoreboard before Test 3")
    print("=" * 50)
    return scoreboard_ok


if __name__ == "__main__":
    asyncio.run(main())
