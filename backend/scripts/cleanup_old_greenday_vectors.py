"""
Delete old GREENDAY manual vectors before adding updated version with ORGANIC
"""

import os
import sys
sys.path.insert(0, '/home/runner/workspace/backend')

from pinecone import Pinecone
from services.rag_utils import get_embedding

def cleanup_old_greenday():
    """Delete old GREENDAY_PRODUCT_MANUAL vectors"""
    
    PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
    
    if not PINECONE_API_KEY or not PINECONE_INDEX_NAME:
        print("❌ Environment variables not set!")
        return
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    print("🔍 Finding old GREENDAY manual vectors...\n")
    
    query_vector = get_embedding("GREENDAY vodka products")
    
    results = index.query(
        vector=query_vector,
        top_k=100,
        namespace="company_knowledge",
        include_metadata=True
    )
    
    to_delete = []
    
    for match in results['matches']:
        vector_id = match['id']
        
        if 'GREENDAY_PRODUCT_MANUAL' in vector_id:
            to_delete.append(vector_id)
            print(f"❌ Will delete: {vector_id}")
    
    print(f"\n📊 Found {len(to_delete)} old GREENDAY manual vectors")
    
    if to_delete:
        print(f"⚠️  These are the old vectors (without ORGANIC)")
        confirm = input(f"\nDelete {len(to_delete)} vectors? (yes/no): ")
        
        if confirm.lower() == 'yes':
            index.delete(ids=to_delete, namespace="company_knowledge")
            
            print(f"\n✅ Deleted {len(to_delete)} old GREENDAY vectors!")
            print(f"🎯 Now run manual_product_ingest.py to add new vectors with ORGANIC!")
        else:
            print("❌ Cleanup cancelled")
    else:
        print("\n✅ No old GREENDAY vectors found!")
        print("🎯 Safe to run manual_product_ingest.py")

if __name__ == "__main__":
    cleanup_old_greenday()
