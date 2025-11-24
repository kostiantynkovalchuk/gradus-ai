"""
Add language support to ContentQueue
Run once to update existing database
"""

import os
import sys

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
import models

def migrate():
    """Add language and needs_translation columns to content_queue table"""
    
    # Initialize database connection
    models.init_db()
    db = models.SessionLocal()
    
    try:
        print("🔄 Starting migration: Add language support...")
        
        # Add language column
        print("  Adding 'language' column...")
        db.execute(text("""
            ALTER TABLE content_queue 
            ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en'
        """))
        
        # Add needs_translation column
        print("  Adding 'needs_translation' column...")
        db.execute(text("""
            ALTER TABLE content_queue 
            ADD COLUMN IF NOT EXISTS needs_translation BOOLEAN DEFAULT TRUE
        """))
        
        # Add posted_at column if it doesn't exist
        print("  Adding 'posted_at' column...")
        db.execute(text("""
            ALTER TABLE content_queue 
            ADD COLUMN IF NOT EXISTS posted_at TIMESTAMP
        """))
        
        db.commit()
        print("✅ Migration completed successfully!")
        print("   - Added 'language' column (default: 'en')")
        print("   - Added 'needs_translation' column (default: TRUE)")
        print("   - Added 'posted_at' column")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
