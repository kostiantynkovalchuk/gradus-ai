-- HR Knowledge Base Schema for Maya HR Bot
-- Migration: 003_hr_knowledge_schema.sql

-- Table: hr_content - Main content storage
CREATE TABLE IF NOT EXISTS hr_content (
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
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: hr_menu_structure - Menu navigation
CREATE TABLE IF NOT EXISTS hr_menu_structure (
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
);

-- Table: hr_embeddings - Vector storage tracking
CREATE TABLE IF NOT EXISTS hr_embeddings (
    id SERIAL PRIMARY KEY,
    content_id VARCHAR(100) REFERENCES hr_content(content_id) ON DELETE CASCADE,
    chunk_index INTEGER,
    chunk_text TEXT NOT NULL,
    embedding_vector TEXT,
    pinecone_id VARCHAR(200) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table: hr_preset_answers - Quick responses
CREATE TABLE IF NOT EXISTS hr_preset_answers (
    id SERIAL PRIMARY KEY,
    question_pattern VARCHAR(500) NOT NULL,
    answer_text TEXT NOT NULL,
    content_ids TEXT[],
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_hr_content_category ON hr_content(category);
CREATE INDEX IF NOT EXISTS idx_hr_content_type ON hr_content(content_type);
CREATE INDEX IF NOT EXISTS idx_hr_content_keywords ON hr_content USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_hr_menu_parent ON hr_menu_structure(parent_id);
CREATE INDEX IF NOT EXISTS idx_hr_embeddings_content ON hr_embeddings(content_id);
CREATE INDEX IF NOT EXISTS idx_preset_active ON hr_preset_answers(is_active, priority DESC);
