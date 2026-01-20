#!/usr/bin/env python3
"""
Script to parse and upload HR knowledge base to Pinecone and PostgreSQL

Usage:
    cd backend && python scripts/upload_hr_data.py

Or with custom data file:
    cd backend && python scripts/upload_hr_data.py --input data/hr_knowledge_base.txt
"""

import asyncio
import sys
import os
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main(input_file: str):
    """Upload HR knowledge base"""
    
    logger.info("=" * 60)
    logger.info("HR Knowledge Base Upload Script")
    logger.info("=" * 60)
    
    from models import init_db, get_db
    init_db()
    db_session = next(get_db())
    
    PINECONE_AVAILABLE = False
    pinecone_index = None
    
    try:
        from pinecone import Pinecone
        
        pinecone_key = os.getenv("PINECONE_API_KEY")
        if pinecone_key:
            pc = Pinecone(api_key=pinecone_key)
            INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
            pinecone_index = pc.Index(INDEX_NAME)
            PINECONE_AVAILABLE = True
            logger.info(f"Connected to Pinecone index: {INDEX_NAME}")
        else:
            logger.warning("PINECONE_API_KEY not set")
    except Exception as e:
        logger.error(f"Pinecone connection error: {e}")
    
    if not PINECONE_AVAILABLE:
        logger.error("Pinecone is required for HR RAG system. Please set PINECONE_API_KEY.")
        return
    
    if not os.path.exists(input_file):
        logger.error(f"Input file not found: {input_file}")
        logger.info("Please create the HR knowledge base file first.")
        logger.info("Expected format: Markdown with sections and numbered questions")
        return
    
    from services.hr_content_processor import HRContentProcessor
    
    processor = HRContentProcessor()
    
    logger.info(f"Reading content from: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        doc_text = f.read()
    
    logger.info(f"Document size: {len(doc_text)} characters")
    
    logger.info("\n1. Parsing content...")
    items = processor.parse_google_doc(doc_text)
    logger.info(f"   Found {len(items)} content items")
    
    if not items:
        logger.warning("No content items found. Check the document format.")
        return
    
    logger.info("\n2. Creating chunks...")
    chunks = processor.create_chunks(items)
    logger.info(f"   Created {len(chunks)} chunks")
    
    logger.info("\n3. Generating embeddings...")
    logger.info("   This may take a few minutes...")
    chunks_with_embeddings = processor.generate_embeddings(chunks)
    logger.info(f"   Generated {len(chunks_with_embeddings)} embeddings")
    
    logger.info("\n4. Uploading to Pinecone (namespace: hr_docs)...")
    pinecone_ids = await processor.upload_to_pinecone(
        chunks_with_embeddings, 
        pinecone_index,
        namespace="hr_docs"
    )
    logger.info(f"   Uploaded {len(pinecone_ids)} vectors")
    
    logger.info("\n5. Storing in PostgreSQL...")
    await processor.store_in_database(items, chunks, pinecone_ids, db_session)
    logger.info("   Database updated")
    
    logger.info("\n6. Generating preset answers...")
    preset_count = await processor.generate_presets(db_session)
    logger.info(f"   Created {preset_count} preset answers")
    
    logger.info("\n" + "=" * 60)
    logger.info("UPLOAD COMPLETE!")
    logger.info("=" * 60)
    logger.info(f"   Content items: {len(items)}")
    logger.info(f"   Total chunks:  {processor.total_chunks}")
    logger.info(f"   Embeddings:    {len(chunks_with_embeddings)}")
    logger.info(f"   Presets:       {processor.total_presets}")
    logger.info("")
    logger.info("Test the HR RAG system:")
    logger.info("   curl -X POST http://localhost:5000/api/hr/answer \\")
    logger.info('        -H "Content-Type: application/json" \\')
    logger.info('        -d \'{"query": "коли виплачують зарплату?"}\'')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload HR knowledge base")
    parser.add_argument(
        "--input", "-i",
        default="data/hr_knowledge_base.txt",
        help="Path to HR knowledge base file (default: data/hr_knowledge_base.txt)"
    )
    
    args = parser.parse_args()
    
    asyncio.run(main(args.input))
