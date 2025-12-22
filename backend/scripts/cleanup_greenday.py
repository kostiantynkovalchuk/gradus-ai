"""
Delete old GREENDAY chunks and keep only manually ingested product data
"""

import os
import sys
sys.path.insert(0, '/home/runner/workspace/backend')

from pinecone import Pinecone

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")

def cleanup_old_greenday():
    """Delete old GREENDAY chunks, keep only PRODUCT manual chunks"""
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    print("🔍 Querying for all GREENDAY-related vectors...")
    
    from services.rag_utils import get_embedding
    query_vector = get_embedding("GREENDAY vodka products")
    
    results = index.query(
        vector=query_vector,
        top_k=100,
        namespace="company_knowledge",
        include_metadata=True
    )
    
    print(f"📊 Found {len(results['matches'])} potential GREENDAY vectors\n")
    
    to_delete = []
    to_keep = []
    
    for match in results['matches']:
        vector_id = match['id']
        metadata = match.get('metadata', {})
        brand = metadata.get('brand', 'N/A')
        content_type = metadata.get('content_type', 'N/A')
        text = metadata.get('text', '')[:100]
        
        if 'GREENDAY_PRODUCT_MANUAL' in vector_id:
            to_keep.append({
                'id': vector_id,
                'brand': brand,
                'type': content_type
            })
            print(f"✅ KEEP: {vector_id[:50]}... | {content_type}")
        
        elif 'greenday' in text.lower() or brand == 'GREENDAY':
            to_delete.append(vector_id)
            print(f"❌ DELETE: {vector_id[:50]}... | {brand} | {content_type}")
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Keeping: {len(to_keep)} manually ingested PRODUCT chunks")
    print(f"   ❌ Deleting: {len(to_delete)} old/bad chunks")
    
    if to_delete:
        confirm = input(f"\n⚠️  DELETE {len(to_delete)} vectors? (yes/no): ")
        if confirm.lower() == 'yes':
            batch_size = 100
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i+batch_size]
                index.delete(ids=batch, namespace="company_knowledge")
                print(f"   🗑️  Deleted batch {i//batch_size + 1}")
            
            print(f"\n✅ Cleanup complete!")
            print(f"   Maya will now see only accurate GREENDAY data!")
        else:
            print("❌ Cleanup cancelled")
    else:
        print("\n✅ No cleanup needed!")

if __name__ == "__main__":
    cleanup_old_greenday()
