"""
One-time broadcast script: AV Post announcement to all active HR employees.

Usage:
  python backend/scripts/broadcast_avpost.py --dry-run   # preview only
  python backend/scripts/broadcast_avpost.py             # send to everyone
"""
import asyncio
import os
import sys
import argparse

import psycopg2
from telegram import Bot
from telegram.constants import ParseMode

# ── message text (MarkdownV2 escaping already applied) ──────────────────────
MESSAGE = (
    "Всім привіт\\! 👋\n\n"
    "Рада оголосити про вихід першого номера корпоративної газети *AV Post* "
    "— нашого нового внутрішнього медіа\\.\n\n"
    "📌 Новини компанії, кейси з полів, аналітика ринку та інсайти від команди "
    "— все в одному місці\\.\n\n"
    "👉 [Читати перший номер](https://avpost-bestbrands.vercel.app/)\n\n"
    "_З повагою, команда AVTD_"
)


def get_active_employees() -> list[tuple[int, str, int]]:
    """Return list of (id, full_name, telegram_id) for active employees."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, full_name, telegram_id
                FROM hr_users
                WHERE telegram_id IS NOT NULL
                  AND is_active = true
                ORDER BY id
                """
            )
            return cur.fetchall()
    finally:
        conn.close()


async def broadcast(employees: list[tuple], dry_run: bool) -> None:
    token = os.environ.get("TELEGRAM_MAYA_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_MAYA_BOT_TOKEN environment variable is not set")

    total = len(employees)
    sent = 0
    errors = 0

    if dry_run:
        print(f"\n── DRY RUN ──────────────────────────────────────")
        print(f"📋 Всього співробітників для розсилки: {total}")
        print(f"Перші 3 записи:")
        for row in employees[:3]:
            emp_id, name, tg_id = row
            print(f"  id={emp_id}  name={name!r}  telegram_id={tg_id}")
        print(f"────────────────────────────────────────────────")
        print("Запустіть без --dry-run щоб надіслати повідомлення.")
        return

    print(f"\n📤 Надсилаємо {total} повідомлень...")
    bot = Bot(token=token)

    for row in employees:
        emp_id, name, tg_id = row
        try:
            await bot.send_message(
                chat_id=tg_id,
                text=MESSAGE,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            sent += 1
            print(f"  ✅ [{sent}/{total}] {name} (tg_id={tg_id})")
        except Exception as e:
            errors += 1
            print(f"  ❌ ПОМИЛКА [{name}, tg_id={tg_id}]: {e}")

        await asyncio.sleep(0.3)

    print(f"\n{'='*48}")
    print(f"✅ Надіслано:              {sent}")
    print(f"❌ Помилок:               {errors}")
    print(f"📋 Всього співробітників: {total}")
    print(f"{'='*48}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AV Post broadcast to HR employees")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    employees = get_active_employees()
    asyncio.run(broadcast(employees, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
