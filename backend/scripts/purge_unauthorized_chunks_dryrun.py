"""
Phase 3 — Dry-run: count chunks that would be deleted from solomon-contracts-corpus.

Run this FIRST. Review the counts. Then run purge_unauthorized_chunks.py.

Usage: cd backend && python scripts/purge_unauthorized_chunks_dryrun.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinecone import Pinecone
import openai

NAMESPACE = "solomon-contracts-corpus"
assert NAMESPACE == "solomon-contracts-corpus", "Wrong namespace — would corrupt other products"

# URLs stored in chunk metadata (with /print1 suffix as used during ingestion)
UNAUTHORIZED_URLS = [
    # Not on approved list
    "https://zakon.rada.gov.ua/laws/show/436-15/print1",              # ГК (74 chunks)
    "https://zakon.rada.gov.ua/laws/show/771/97-%D0%B2%D1%80/print1", # Безпечність харч. (81)
    "https://zakon.rada.gov.ua/laws/show/2275-19/print1",             # Товариства (61)
    "https://zakon.rada.gov.ua/laws/show/2210-14/print1",             # Екон. конкуренція (76)
    "https://zakon.rada.gov.ua/laws/show/236/96-%D0%B2%D1%80/print1", # Недоброс. конкур. (30)
    # Superseded — old versions of approved laws
    "https://zakon.rada.gov.ua/laws/show/481/95-%D0%B2%D1%80/print1", # Old спирт (64, replaced by 3817-20)
    "https://zakon.rada.gov.ua/laws/show/3792-12/print1",             # Old авт. право (64, replaced by 2811-20)
    # Not in approved list (was added to original corpus by mistake)
    "https://zakon.rada.gov.ua/laws/show/187-2022-%D0%BF/print1",     # КМУ №187 (3)
]


def main():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    idx = pc.Index("gradus-media")

    # Capture before stats
    stats_before = idx.describe_index_stats()
    print("=== BEFORE STATS ===")
    for ns, info in stats_before.namespaces.items():
        print(f"  {ns}: {info.vector_count} vectors")

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    print("\n=== DRY-RUN: chunks that would be deleted ===")
    total = 0
    for url in UNAUTHORIZED_URLS:
        # Use a real embedding to trigger meaningful similarity results with filter
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=url.split("/")[-1].replace("print1", "").replace("-", " ")[:100],
        )
        vec = resp.data[0].embedding

        # Query in batches — Pinecone top_k max is 10000
        result = idx.query(
            namespace=NAMESPACE,
            vector=vec,
            top_k=1000,
            include_metadata=True,
            filter={"official_url": {"$eq": url}},
        )
        n = len(result.matches)
        total += n
        print(f"  {url.split('show/')[-1]}: {n} chunks would be deleted")

    print(f"\nTotal to delete: {total}")
    print(f"Remaining after cleanup: ~{stats_before.namespaces.get(NAMESPACE, type('', (), {'vector_count': '?'})()).vector_count} - {total}")
    print("\nReview counts above, then run purge_unauthorized_chunks.py to execute.")


if __name__ == "__main__":
    main()
