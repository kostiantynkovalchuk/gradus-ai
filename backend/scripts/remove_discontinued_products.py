"""
Remove discontinued products (Marlin, Adjari) from Pinecone vector database
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinecone import Pinecone
from openai import OpenAI

pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index(os.getenv('PINECONE_INDEX_NAME', 'gradus-media'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def get_embedding(text):
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

search_terms = [
    'marlin vodka', 'марлін горілка', 'marlin водка',
    'adjari cognac', 'аджарі коньяк', 'adjari коньяк',
    'adjari wine', 'аджарі вино'
]

print("🔍 Searching for discontinued products in vector DB...")

total_deleted = 0
all_ids_to_delete = set()

for term in search_terms:
    print(f"\n📍 Searching: {term}")
    query_embedding = get_embedding(term)
    
    results = index.query(
        vector=query_embedding,
        top_k=50,
        include_metadata=True
    )
    
    for match in results.matches:
        metadata_text = str(match.metadata).lower()
        if any(word in metadata_text for word in ['marlin', 'marlín', 'марлін', 'adjari', 'аджарі']):
            all_ids_to_delete.add(match.id)
            source = match.metadata.get('source', 'unknown')[:50]
            print(f"  📌 Found: {match.id[:30]}... | score: {match.score:.3f} | source: {source}")

if all_ids_to_delete:
    ids_list = list(all_ids_to_delete)
    print(f"\n🗑️ Deleting {len(ids_list)} entries...")
    
    batch_size = 100
    for i in range(0, len(ids_list), batch_size):
        batch = ids_list[i:i+batch_size]
        index.delete(ids=batch)
        print(f"  ✅ Deleted batch {i//batch_size + 1}: {len(batch)} entries")
    
    total_deleted = len(ids_list)
else:
    print("\n✅ No discontinued products found in vector DB")

print(f"\n🎉 Cleanup complete! Total deleted: {total_deleted}")
