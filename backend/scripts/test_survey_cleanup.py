"""
POST-TEST CLEANUP — Reset survey state after all 3 tests pass.
Deletes test votes and meta; resets sent_count to 0.
The hr_surveys seed row (easter_holiday_2026) is preserved.

Usage:
  cd /home/runner/workspace && python backend/scripts/test_survey_cleanup.py
"""
import os
import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "")


def run():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("DELETE FROM hr_survey_votes WHERE survey_id = 'easter_holiday_2026'")
    deleted_votes = cur.rowcount

    cur.execute("DELETE FROM hr_survey_meta WHERE survey_id = 'easter_holiday_2026'")
    deleted_meta = cur.rowcount

    cur.execute("UPDATE hr_surveys SET sent_count = 0 WHERE survey_id = 'easter_holiday_2026'")

    cur.execute("SELECT is_open, sent_count FROM hr_surveys WHERE survey_id = 'easter_holiday_2026'")
    row = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    print("🧹 Cleanup complete:")
    print(f"   Votes deleted:    {deleted_votes}")
    print(f"   Meta deleted:     {deleted_meta}")
    print(f"   is_open:          {row[0]}")
    print(f"   sent_count reset: {row[1]}")
    print()
    print("✅ System ready for live broadcast on April 7 at 10:00 Kyiv")


if __name__ == "__main__":
    run()
