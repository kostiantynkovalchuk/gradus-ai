"""
Backfill existing articles into Pinecone
Run once to add all your 160+ existing articles to Maya's knowledge base
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import get_db
from services.rag_utils import ingest_existing_articles
import asyncio
from pinecone import Pinecone

async def main():
    """Backfill all existing articles"""
    
    print("🚀 Starting article backfill to Pinecone...")
    print("=" * 60)
    
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if not pinecone_key:
        print("❌ PINECONE_API_KEY not set!")
        return
    
    pc = Pinecone(api_key=pinecone_key)
    index_name = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
    index = pc.Index(index_name)
    
    print(f"✅ Connected to Pinecone index: {index_name}")
    
    db = next(get_db())
    
    print("\n📚 Ingesting most recent 50 articles...\n")
    
    result = await ingest_existing_articles(db, index, limit=50)
    
    print("\n" + "=" * 60)
    print("📊 BACKFILL RESULTS:")
    print(f"   Total articles processed: {result.get('total', 0)}")
    print(f"   Successfully ingested: {result.get('success', 0)}")
    print(f"   Failed: {result.get('failed', 0)}")
    
    if result.get('error'):
        print(f"   ❌ Error: {result['error']}")
    else:
        print("\n✅ Backfill complete! Maya now knows your articles!")
    
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
