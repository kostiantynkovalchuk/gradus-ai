import os
import psycopg2


def get_db_connection():
    return psycopg2.connect(os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL"))
