import os
import logging
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

MIGRATIONS = [
    {
        "version": "001_initial_tables",
        "statements": [
            """CREATE TABLE IF NOT EXISTS content_queue (
                id SERIAL PRIMARY KEY,
                status VARCHAR(20) NOT NULL CHECK (status IN ('draft', 'pending_approval', 'approved', 'rejected', 'posted', 'posting_facebook', 'posting_linkedin')),
                source VARCHAR(255),
                source_url VARCHAR(500),
                source_title TEXT,
                original_text TEXT,
                translated_title TEXT,
                translated_text TEXT,
                image_url TEXT,
                image_prompt TEXT,
                local_image_path TEXT,
                image_data BYTEA,
                scheduled_post_time TIMESTAMP,
                platforms TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewed_by VARCHAR(100),
                rejection_reason TEXT,
                edit_history JSONB,
                extra_metadata JSONB,
                analytics JSONB,
                posted_at TIMESTAMP,
                language VARCHAR(10) DEFAULT 'en',
                needs_translation BOOLEAN DEFAULT TRUE,
                notification_sent BOOLEAN DEFAULT FALSE,
                category VARCHAR(50),
                image_credit VARCHAR(255),
                image_credit_url VARCHAR(500),
                image_photographer VARCHAR(255),
                unsplash_image_id VARCHAR(100),
                last_tier_used INTEGER,
                tier_attempts JSONB
            )""",
            """CREATE TABLE IF NOT EXISTS approval_log (
                id SERIAL PRIMARY KEY,
                content_id INTEGER NOT NULL,
                action VARCHAR(50),
                moderator VARCHAR(100),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details JSONB
            )""",
            """CREATE TABLE IF NOT EXISTS media_files (
                id SERIAL PRIMARY KEY,
                media_type VARCHAR(50) NOT NULL,
                media_key VARCHAR(100) NOT NULL UNIQUE,
                file_id VARCHAR(255) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
    },
    {
        "version": "002_maya_users",
        "statements": [
            """CREATE TABLE IF NOT EXISTS maya_users (
                email VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                position VARCHAR(100),
                questions_today INTEGER DEFAULT 0,
                questions_limit INTEGER DEFAULT 5,
                last_question_at TIMESTAMP,
                last_reset_date DATE DEFAULT CURRENT_DATE,
                subscription_tier VARCHAR(50) DEFAULT 'free' CHECK (subscription_tier IN ('free', 'standard', 'premium')),
                subscription_status VARCHAR(50) DEFAULT 'active' CHECK (subscription_status IN ('active', 'cancelled', 'expired', 'trial')),
                subscription_started_at TIMESTAMP,
                subscription_expires_at TIMESTAMP,
                wayforpay_order_id VARCHAR(255),
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS maya_subscriptions (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                tier VARCHAR(50) NOT NULL CHECK (tier IN ('standard', 'premium')),
                billing_cycle VARCHAR(20) NOT NULL CHECK (billing_cycle IN ('monthly', 'annual')),
                amount DECIMAL(10,2) NOT NULL,
                currency VARCHAR(3) DEFAULT 'USD',
                wayforpay_order_id VARCHAR(255) UNIQUE,
                payment_status VARCHAR(50) DEFAULT 'pending' CHECK (payment_status IN ('pending', 'success', 'failed', 'refunded')),
                payment_data JSONB,
                started_at TIMESTAMP,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS maya_query_log (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                query_text TEXT NOT NULL,
                response_text TEXT,
                tokens_used INTEGER,
                response_time_ms INTEGER,
                session_id VARCHAR(255),
                user_tier VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
    },
    {
        "version": "003_hr_tables",
        "statements": [
            """CREATE TABLE IF NOT EXISTS hr_content (
                id SERIAL PRIMARY KEY,
                content_id VARCHAR(100) UNIQUE NOT NULL,
                content_type VARCHAR(50) NOT NULL,
                title VARCHAR(500) NOT NULL,
                content TEXT NOT NULL,
                category VARCHAR(100),
                subcategory VARCHAR(100),
                keywords TEXT[],
                metadata JSONB,
                video_url VARCHAR(500),
                attachments JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_menu_structure (
                id SERIAL PRIMARY KEY,
                menu_id VARCHAR(100) UNIQUE NOT NULL,
                parent_id VARCHAR(100),
                title VARCHAR(200) NOT NULL,
                emoji VARCHAR(10),
                order_index INTEGER,
                button_type VARCHAR(50),
                content_id VARCHAR(100),
                metadata JSONB,
                is_active BOOLEAN DEFAULT TRUE
            )""",
            """CREATE TABLE IF NOT EXISTS hr_embeddings (
                id SERIAL PRIMARY KEY,
                content_id VARCHAR(100) NOT NULL,
                chunk_index INTEGER,
                chunk_text TEXT NOT NULL,
                embedding_vector TEXT,
                pinecone_id VARCHAR(200) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_preset_answers (
                id SERIAL PRIMARY KEY,
                question_pattern VARCHAR(500) NOT NULL,
                answer_text TEXT NOT NULL,
                content_ids TEXT[],
                category VARCHAR(50),
                priority INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                usage_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_documents (
                id SERIAL PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                document_type VARCHAR(50),
                document_number VARCHAR(50),
                url TEXT NOT NULL,
                access_level VARCHAR(50) DEFAULT 'all',
                topics TEXT[],
                keywords TEXT[],
                category VARCHAR(100),
                description TEXT,
                file_format VARCHAR(50) DEFAULT 'google_doc',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_hr_documents_number ON hr_documents(document_number)",
            "CREATE INDEX IF NOT EXISTS idx_hr_documents_topics ON hr_documents USING GIN(topics)",
            "CREATE INDEX IF NOT EXISTS idx_hr_documents_keywords ON hr_documents USING GIN(keywords)",
        ]
    },
    {
        "version": "004_hr_auth",
        "statements": [
            """CREATE TABLE IF NOT EXISTS hr_users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                phone VARCHAR(20),
                employee_id VARCHAR(50),
                full_name VARCHAR(255),
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                department VARCHAR(200),
                position VARCHAR(200),
                start_date VARCHAR(50),
                email VARCHAR(255),
                access_level VARCHAR(20) DEFAULT 'employee',
                verification_method VARCHAR(50) DEFAULT 'sed_api',
                manually_added_by INTEGER,
                notes TEXT,
                last_sed_sync TIMESTAMP,
                sed_sync_status VARCHAR(50),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_whitelist (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) UNIQUE NOT NULL,
                telegram_id BIGINT UNIQUE,
                full_name VARCHAR(255) NOT NULL,
                access_level VARCHAR(20) DEFAULT 'contractor',
                reason TEXT,
                added_by VARCHAR(255),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )""",
            "CREATE INDEX IF NOT EXISTS idx_hr_whitelist_phone ON hr_whitelist(phone)",
            """CREATE TABLE IF NOT EXISTS verification_log (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                phone VARCHAR(20),
                employee_id VARCHAR(50),
                verification_type VARCHAR(50),
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
    },
    {
        "version": "005_hr_analytics",
        "statements": [
            """CREATE TABLE IF NOT EXISTS hr_query_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                user_name VARCHAR(255),
                query TEXT,
                query_normalized TEXT,
                preset_matched BOOLEAN,
                preset_id INTEGER,
                rag_used BOOLEAN,
                content_ids TEXT[],
                response_time_ms INTEGER,
                satisfied BOOLEAN,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_feedback (
                id SERIAL PRIMARY KEY,
                query_log_id INTEGER,
                user_id BIGINT,
                feedback_type VARCHAR(50),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS hr_daily_stats (
                id SERIAL PRIMARY KEY,
                date DATE,
                total_queries INTEGER,
                preset_hits INTEGER,
                rag_queries INTEGER,
                unique_users INTEGER,
                avg_response_time_ms INTEGER,
                satisfaction_rate DECIMAL(5,2),
                top_categories JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
    },
    {
        "version": "006_alex_presets",
        "statements": [
            """CREATE TABLE IF NOT EXISTS alex_preset_answers (
                id SERIAL PRIMARY KEY,
                question_pattern VARCHAR(500) NOT NULL,
                answer_text TEXT NOT NULL,
                category VARCHAR(50) DEFAULT 'general',
                priority INTEGER DEFAULT 5,
                usage_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_alex_preset_category ON alex_preset_answers(category)",
            "CREATE INDEX IF NOT EXISTS idx_alex_preset_active ON alex_preset_answers(is_active)",
        ]
    },
    {
        "version": "007_alex_preset_candidates",
        "statements": [
            """CREATE TABLE IF NOT EXISTS alex_preset_candidates (
                id SERIAL PRIMARY KEY,
                question_text TEXT NOT NULL,
                frequency INTEGER DEFAULT 1,
                avg_response_time_ms INTEGER,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) DEFAULT 'candidate',
                promoted_preset_id INTEGER REFERENCES alex_preset_answers(id),
                sample_claude_answer TEXT,
                dominant_tier VARCHAR(20) DEFAULT 'free'
            )""",
        ]
    },
    {
        "version": "008_content_queue_extras",
        "statements": [
            "ALTER TABLE content_queue ADD COLUMN IF NOT EXISTS category VARCHAR(50)",
            "ALTER TABLE content_queue ADD COLUMN IF NOT EXISTS image_photographer VARCHAR(255)",
            "CREATE INDEX IF NOT EXISTS idx_content_category ON content_queue(category)",
        ]
    },
    {
        "version": "009_maya_users_position",
        "statements": [
            "ALTER TABLE maya_users ADD COLUMN IF NOT EXISTS position VARCHAR(100)",
        ]
    },
]


def run_migrations():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set — skipping migrations")
        return

    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

        result = conn.execute(text("SELECT version FROM schema_migrations"))
        applied = {row[0] for row in result}

        pending = 0
        for migration in MIGRATIONS:
            version = migration["version"]
            if version in applied:
                logger.info(f"Migration {version} — already applied, skipping")
                continue

            try:
                for statement in migration["statements"]:
                    statement = statement.strip()
                    if statement:
                        conn.execute(text(statement))
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                    {"v": version}
                )
                conn.commit()
                logger.info(f"Migration {version} — applied successfully")
                pending += 1
            except Exception as e:
                conn.rollback()
                logger.error(f"Migration {version} FAILED: {e}")
                raise

        if pending == 0:
            logger.info("All migrations already applied — database is up to date")
        else:
            logger.info(f"Applied {pending} new migration(s)")

    engine.dispose()
