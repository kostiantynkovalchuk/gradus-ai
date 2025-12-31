#!/usr/bin/env python3
"""
Database Initialization Script for Gradus Media AI Agent

This script ensures the database schema is up-to-date by:
1. Creating tables if they don't exist (via SQLAlchemy)
2. Adding missing columns to existing tables
3. Creating indexes for performance

Safe to run multiple times (idempotent).

Usage:
    Local:  cd backend && python init_db.py
    Render: python init_db.py
"""

import os
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    'content_queue': [
        ('status', 'VARCHAR(20)'),
        ('source', 'VARCHAR(255)'),
        ('source_url', 'VARCHAR(500)'),
        ('source_title', 'TEXT'),
        ('original_text', 'TEXT'),
        ('translated_title', 'TEXT'),
        ('translated_text', 'TEXT'),
        ('image_url', 'TEXT'),
        ('image_prompt', 'TEXT'),
        ('local_image_path', 'TEXT'),
        ('image_data', 'BYTEA'),
        ('scheduled_post_time', 'TIMESTAMP'),
        ('platforms', 'VARCHAR(50)[]'),
        ('created_at', 'TIMESTAMP DEFAULT NOW()'),
        ('reviewed_at', 'TIMESTAMP'),
        ('reviewed_by', 'VARCHAR(100)'),
        ('rejection_reason', 'TEXT'),
        ('edit_history', 'JSON'),
        ('extra_metadata', 'JSON'),
        ('analytics', 'JSON'),
        ('posted_at', 'TIMESTAMP'),
        ('language', "VARCHAR(10) DEFAULT 'en'"),
        ('needs_translation', 'BOOLEAN DEFAULT TRUE'),
        ('notification_sent', 'BOOLEAN DEFAULT FALSE'),
        ('category', 'VARCHAR(20)'),
    ],
    'approval_log': [
        ('content_id', 'INTEGER'),
        ('action', 'VARCHAR(50)'),
        ('moderator', 'VARCHAR(100)'),
        ('timestamp', 'TIMESTAMP DEFAULT NOW()'),
        ('details', 'JSON'),
    ]
}

def get_connection():
    """Get database connection using DATABASE_URL"""
    try:
        import psycopg2
    except ImportError:
        logger.error("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        logger.info("Connected to database successfully")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

def table_exists(cursor, table_name):
    """Check if a table exists"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = %s
        )
    """, (table_name,))
    return cursor.fetchone()[0]

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = %s 
            AND column_name = %s
        )
    """, (table_name, column_name))
    return cursor.fetchone()[0]

def get_existing_columns(cursor, table_name):
    """Get list of existing columns in a table"""
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = %s
    """, (table_name,))
    return [row[0] for row in cursor.fetchall()]

def add_missing_columns(cursor, table_name, required_columns):
    """Add any missing columns to an existing table"""
    existing = set(get_existing_columns(cursor, table_name))
    added = []
    
    for col_name, col_type in required_columns:
        if col_name.lower() not in [c.lower() for c in existing]:
            sql = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            logger.info(f"  Adding column: {table_name}.{col_name} ({col_type})")
            try:
                cursor.execute(sql)
                added.append(col_name)
            except Exception as e:
                logger.warning(f"  Could not add {col_name}: {e}")
    
    return added

def create_tables_via_sqlalchemy():
    """Create tables using SQLAlchemy models"""
    try:
        from models import init_db
        init_db()
        logger.info("SQLAlchemy tables created/verified")
        return True
    except Exception as e:
        logger.warning(f"SQLAlchemy init failed (may be OK): {e}")
        return False

def init_database():
    """Main database initialization function"""
    logger.info("=" * 60)
    logger.info("Gradus Media AI Agent - Database Initialization")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    
    create_tables_via_sqlalchemy()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        changes_made = False
        
        for table_name, columns in REQUIRED_COLUMNS.items():
            logger.info(f"\nProcessing table: {table_name}")
            
            if not table_exists(cursor, table_name):
                logger.warning(f"  Table {table_name} does not exist - run SQLAlchemy migration first")
                continue
            
            existing = get_existing_columns(cursor, table_name)
            logger.info(f"  Found {len(existing)} existing columns")
            
            added = add_missing_columns(cursor, table_name, columns)
            if added:
                changes_made = True
                logger.info(f"  Added {len(added)} column(s): {', '.join(added)}")
            else:
                logger.info(f"  All required columns present")
        
        conn.commit()
        logger.info("\n" + "=" * 60)
        if changes_made:
            logger.info("Database initialization completed with changes")
        else:
            logger.info("Database initialization completed (no changes needed)")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"\nDatabase initialization failed: {e}")
        logger.error("Changes have been rolled back")
        raise
    finally:
        cursor.close()
        conn.close()

def show_current_schema():
    """Display current database schema for debugging"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        logger.info("\n" + "=" * 60)
        logger.info("Current Database Schema")
        logger.info("=" * 60)
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        for (table_name,) in tables:
            logger.info(f"\nTable: {table_name}")
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            
            for col in cursor.fetchall():
                col_name, data_type, nullable, default = col
                nullable_str = "NULL" if nullable == 'YES' else "NOT NULL"
                default_str = f" DEFAULT {default[:30]}..." if default and len(str(default)) > 30 else (f" DEFAULT {default}" if default else "")
                logger.info(f"  - {col_name}: {data_type} {nullable_str}{default_str}")
        
    finally:
        cursor.close()
        conn.close()

def verify_schema():
    """Verify the database schema has all required columns"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        issues = []
        
        for table_name, columns in REQUIRED_COLUMNS.items():
            if not table_exists(cursor, table_name):
                issues.append(f"Missing table: {table_name}")
                continue
            
            existing = set(c.lower() for c in get_existing_columns(cursor, table_name))
            
            for col_name, _ in columns:
                if col_name.lower() not in existing:
                    issues.append(f"Missing column: {table_name}.{col_name}")
        
        return issues
        
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize Gradus AI database')
    parser.add_argument('--show-schema', action='store_true', help='Show current schema')
    parser.add_argument('--verify-only', action='store_true', help='Only verify, do not modify')
    args = parser.parse_args()
    
    if args.show_schema:
        show_current_schema()
    elif args.verify_only:
        issues = verify_schema()
        
        if issues:
            logger.warning("Schema issues found:")
            for issue in issues:
                logger.warning(f"  - {issue}")
            sys.exit(1)
        else:
            logger.info("Schema verification passed - all required columns present")
    else:
        init_database()
