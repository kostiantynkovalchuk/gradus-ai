-- HR Bot Analytics & Query Logging
-- Run this migration to create analytics tables

-- Query log table
CREATE TABLE IF NOT EXISTS hr_query_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    user_name VARCHAR(200),
    query TEXT NOT NULL,
    query_normalized TEXT,
    preset_matched BOOLEAN DEFAULT FALSE,
    preset_id INTEGER,
    rag_used BOOLEAN DEFAULT FALSE,
    content_ids TEXT[],
    response_time_ms INTEGER,
    satisfied BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Feedback table
CREATE TABLE IF NOT EXISTS hr_feedback (
    id SERIAL PRIMARY KEY,
    query_log_id INTEGER REFERENCES hr_query_log(id),
    user_id BIGINT NOT NULL,
    feedback_type VARCHAR(50),
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Daily stats aggregation
CREATE TABLE IF NOT EXISTS hr_daily_stats (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    total_queries INTEGER DEFAULT 0,
    preset_hits INTEGER DEFAULT 0,
    rag_queries INTEGER DEFAULT 0,
    unique_users INTEGER DEFAULT 0,
    avg_response_time_ms INTEGER DEFAULT 0,
    satisfaction_rate DECIMAL(5,2),
    top_categories JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_query_log_user ON hr_query_log(user_id);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON hr_query_log(created_at);
CREATE INDEX IF NOT EXISTS idx_query_log_preset ON hr_query_log(preset_matched);
CREATE INDEX IF NOT EXISTS idx_query_normalized ON hr_query_log(query_normalized);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON hr_daily_stats(date);
