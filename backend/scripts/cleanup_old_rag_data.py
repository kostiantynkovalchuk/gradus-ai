import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()

def delete_old_company_data():
    """Delete old AVTD and brand website data from Pinecone"""
    
    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")
    
    if not api_key or not index_name:
        print("❌ Missing PINECONE_API_KEY or PINECONE_INDEX_NAME")
        return
    
    pc = Pinecone(api_key=api_key)
    index = pc.Index(index_name)
    
    print("🗑️ Deleting old company website data...")
    
    try:
        index.delete(
            filter={
                "source_type": {"$in": ["company_website", "brand_website"]}
            },
            namespace="company_knowledge"
        )
        print("✅ Deleted old company website data")
        
    except Exception as e:
        print(f"❌ Error deleting data: {e}")
    
    stats = index.describe_index_stats()
    print(f"📊 Remaining vectors: {stats}")

if __name__ == "__main__":
    delete_old_company_data()
