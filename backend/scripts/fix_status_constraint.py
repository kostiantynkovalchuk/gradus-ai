"""Fix database constraint to allow posting statuses"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

def fix_constraint():
    print("🔧 Fixing status constraint...")
    
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE content_queue DROP CONSTRAINT IF EXISTS valid_status;
        """))
        conn.commit()
        
        print("✓ Old constraint dropped")
        
        conn.execute(text("""
            ALTER TABLE content_queue ADD CONSTRAINT valid_status 
            CHECK (status IN ('draft', 'pending_approval', 'approved', 'rejected', 'posted', 'posting_facebook', 'posting_linkedin'));
        """))
        conn.commit()
        
        print("✓ New constraint added")
        
        result = conn.execute(text("""
            SELECT constraint_name, check_clause 
            FROM information_schema.check_constraints 
            WHERE constraint_name = 'valid_status';
        """))
        
        for row in result:
            print(f"\n✅ Constraint verified:")
            print(f"   Name: {row[0]}")
            print(f"   Check: {row[1]}")
    
    print("\n🎉 Database constraint fixed!")

if __name__ == "__main__":
    fix_constraint()
