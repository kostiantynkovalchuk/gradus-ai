from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ARRAY, Boolean, JSON
from sqlalchemy.sql import func
from . import Base


class HRContent(Base):
    """HR Knowledge Base Content Storage"""
    __tablename__ = "hr_content"
    
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(String(100), unique=True, nullable=False)
    content_type = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100))
    subcategory = Column(String(100))
    keywords = Column(ARRAY(String))
    extra_data = Column('metadata', JSON)
    video_url = Column(String(500))
    attachments = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class HRMenuStructure(Base):
    """HR Bot Menu Navigation Structure"""
    __tablename__ = "hr_menu_structure"
    
    id = Column(Integer, primary_key=True, index=True)
    menu_id = Column(String(100), unique=True, nullable=False)
    parent_id = Column(String(100))
    title = Column(String(200), nullable=False)
    emoji = Column(String(10))
    order_index = Column(Integer)
    button_type = Column(String(50))
    content_id = Column(String(100))
    extra_data = Column('metadata', JSON)
    is_active = Column(Boolean, default=True)


class HREmbedding(Base):
    """HR Content Embedding Tracking"""
    __tablename__ = "hr_embeddings"
    
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(String(100), nullable=False)
    chunk_index = Column(Integer)
    chunk_text = Column(Text, nullable=False)
    embedding_vector = Column(Text)
    pinecone_id = Column(String(200), unique=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class HRDocument(Base):
    """HR Documents for Smart Linking to Answers"""
    __tablename__ = "hr_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    document_type = Column(String(50))
    document_number = Column(String(50), index=True)
    url = Column(Text, nullable=False)
    access_level = Column(String(50), default='all')
    topics = Column(ARRAY(String))
    keywords = Column(ARRAY(String))
    category = Column(String(100))
    description = Column(Text)
    file_format = Column(String(50), default='google_doc')
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class HRPresetAnswer(Base):
    """Quick Response Presets for Common HR Questions"""
    __tablename__ = "hr_preset_answers"
    
    id = Column(Integer, primary_key=True, index=True)
    question_pattern = Column(String(500), nullable=False)
    answer_text = Column(Text, nullable=False)
    content_ids = Column(ARRAY(String))
    category = Column(String(50))
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
