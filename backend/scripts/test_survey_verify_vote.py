"""
TEST 3 — DB verification after manual vote (run after tapping button in Telegram).

Usage:
  cd /home/runner/workspace && python backend/scripts/test_survey_verify_vote.py
"""
import os
import psycopg2
from datetime import datetime, timezone

DB_URL = os.environ.get("DATABASE_URL", "")


def run():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("""
        SELECT v.answer, v.voted_at, u.full_name
        FROM hr_survey_votes v
        JOIN hr_users u ON u.id = v.user_id
        WHERE v.survey_id = 'easter_holiday_2026'
    """)
    votes = cur.fetchall()

    print(f"\nVotes in DB: {len(votes)}")
    for v in votes:
        print(f"  {v[2]}: {v[0]} at {v[1]}")

    if len(votes) == 0:
        print("❌ No votes recorded. Did you tap the button?")
        cur.close(); conn.close(); return

    assert len(votes) == 1, f"❌ Expected 1 vote, got {len(votes)}"
    assert votes[0][0] in ("yes", "no"), f"❌ Unexpected answer: {votes[0][0]}"
    print(f"✅ Vote recorded correctly: {votes[0][0]}")

    cur.execute("""
        SELECT last_edit_at, scoreboard_targets
        FROM hr_survey_meta
        WHERE survey_id = 'easter_holiday_2026'
    """)
    meta = cur.fetchone()

    if meta and meta[0]:
        now    = datetime.now(timezone.utc)
        edited = meta[0].replace(tzinfo=timezone.utc) if meta[0].tzinfo is None else meta[0]
        elapsed = (now - edited).total_seconds()
        print(f"✅ Scoreboard last edited {elapsed:.0f}s ago")
        if elapsed > 30:
            print("⚠️  WARNING: last_edit_at > 30s — scoreboard may not have updated on vote")
    else:
        print("⚠️  last_edit_at is NULL — scoreboard edit was not triggered")

    cur.close()
    conn.close()

    print("""
════════════════════════════════════════
TEST 3 MANUAL CHECKLIST
════════════════════════════════════════
After tapping ✅ Так, verify in Telegram:

Konstantin's phone only:
□ Survey message buttons disappeared
□ Replaced with confirmation text:
  "✅ Дякуємо! Ваш голос враховано."
□ Scoreboard message updated (shows 1 голос)

NOTE: Natalia will only receive scoreboard
      during the real broadcast on April 7.
      She is not involved in test runs.

HR Dashboard (/hr Pulse tab):
□ Survey card visible
□ Yes bar shows 100%
□ Total shows 1 проголосували
□ LIVE badge visible
□ "⏹ Закрити опитування" button visible
════════════════════════════════════════
""")


if __name__ == "__main__":
    run()
