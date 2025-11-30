#!/usr/bin/env python3
"""
Database Export Script
Exports the Replit PostgreSQL database to a backup.sql file
"""

import os
import subprocess
import sys
from urllib.parse import urlparse
from datetime import datetime

def export_database():
    """Export PostgreSQL database to backup.sql file"""
    
    print("=" * 50)
    print("PostgreSQL Database Export")
    print("=" * 50)
    
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not found")
        sys.exit(1)
    
    try:
        parsed = urlparse(database_url)
        
        db_host = parsed.hostname
        db_port = parsed.port or 5432
        db_name = parsed.path.lstrip('/')
        db_user = parsed.username
        db_password = parsed.password
        
        print(f"Host: {db_host}")
        print(f"Port: {db_port}")
        print(f"Database: {db_name}")
        print(f"User: {db_user}")
        print("-" * 50)
        
    except Exception as e:
        print(f"ERROR: Failed to parse DATABASE_URL: {e}")
        sys.exit(1)
    
    output_file = "backup.sql"
    
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    
    pg_dump_cmd = [
        "pg_dump",
        "-h", db_host,
        "-p", str(db_port),
        "-U", db_user,
        "-d", db_name,
        "-F", "p",
        "-f", output_file,
        "--no-owner",
        "--no-acl",
        "--clean",
        "--if-exists",
        "--create"
    ]
    
    print(f"Exporting database to {output_file}...")
    print("This may take a moment...")
    print()
    
    try:
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"ERROR: pg_dump failed with exit code {result.returncode}")
            if result.stderr:
                print(f"Error details: {result.stderr}")
            sys.exit(1)
        
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            file_size_kb = file_size / 1024
            file_size_mb = file_size_kb / 1024
            
            print("=" * 50)
            print("EXPORT COMPLETE")
            print("=" * 50)
            print(f"Output file: {output_file}")
            
            if file_size_mb >= 1:
                print(f"File size: {file_size_mb:.2f} MB")
            else:
                print(f"File size: {file_size_kb:.2f} KB")
            
            print(f"Exported at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()
            print("The backup includes:")
            print("  - All table schemas")
            print("  - All table data")
            print("  - All indexes and constraints")
            print("  - DROP/CREATE statements for clean restore")
            print()
            
        else:
            print("ERROR: Output file was not created")
            sys.exit(1)
            
    except FileNotFoundError:
        print("ERROR: pg_dump command not found")
        print("Make sure PostgreSQL client tools are installed")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error during export: {e}")
        sys.exit(1)

if __name__ == "__main__":
    export_database()
