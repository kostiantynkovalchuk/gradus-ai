"""
Phase 3 — Execution: delete unauthorized chunks from solomon-contracts-corpus.

CAUTION: destructive. Run purge_unauthorized_chunks_dryrun.py first.

Usage: cd backend && python scripts/purge_unauthorized_chunks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinecone import Pinecone
import openai

NAMESPACE = "solomon-contracts-corpus"
assert NAMESPACE == "solomon-contracts-corpus", "Wrong namespace — would corrupt other products"

UNAUTHORIZED_URLS = [
    "https://zakon.rada.gov.ua/laws/show/436-15/print1",
    "https://zakon.rada.gov.ua/laws/show/771/97-%D0%B2%D1%80/print1",
    "https://zakon.rada.gov.ua/laws/show/2275-19/print1",
    "https://zakon.rada.gov.ua/laws/show/2210-14/print1",
    "https://zakon.rada.gov.ua/laws/show/236/96-%D0%B2%D1%80/print1",
    "https://zakon.rada.gov.ua/laws/show/481/95-%D0%B2%D1%80/print1",
    "https://zakon.rada.gov.ua/laws/show/3792-12/print1",
    "https://zakon.rada.gov.ua/laws/show/187-2022-%D0%BF/print1",
]

OTHER_NAMESPACES = ("hr_docs", "company_knowledge")


def main():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    idx = pc.Index("gradus-media")

    # Capture counts for other namespaces BEFORE purge
    stats_before = idx.describe_index_stats()
    before_counts = {
        ns: stats_before.namespaces.get(ns, type("", (), {"vector_count": 0})()).vector_count
        for ns in OTHER_NAMESPACES
    }
    solcon_before = stats_before.namespaces.get(NAMESPACE, type("", (), {"vector_count": 0})()).vector_count
    print(f"Before: {NAMESPACE}={solcon_before} vectors")
    for ns, cnt in before_counts.items():
        print(f"  {ns}={cnt} (must not change)")

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    total_deleted = 0
    print("\n=== DELETING unauthorized chunks ===")
    for url in UNAUTHORIZED_URLS:
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=url.split("/")[-1].replace("print1", "").replace("-", " ")[:100],
        )
        vec = resp.data[0].embedding

        result = idx.query(
            namespace=NAMESPACE,
            vector=vec,
            top_k=1000,
            include_metadata=True,
            filter={"official_url": {"$eq": url}},
        )
        ids_to_delete = [m.id for m in result.matches]
        if ids_to_delete:
            idx.delete(ids=ids_to_delete, namespace=NAMESPACE)
            total_deleted += len(ids_to_delete)
            print(f"  Deleted {len(ids_to_delete)} chunks for {url.split('show/')[-1]}")
        else:
            print(f"  No chunks found for {url.split('show/')[-1]} (already clean)")

    print(f"\nTotal deleted: {total_deleted}")

    # Post-purge sanity checks
    print("\n=== SANITY CHECKS ===")
    stats_after = idx.describe_index_stats()
    solcon_after = stats_after.namespaces.get(NAMESPACE, type("", (), {"vector_count": 0})()).vector_count
    print(f"{NAMESPACE}: {solcon_before} → {solcon_after} (expected ~{solcon_before - total_deleted})")

    # Confirm other namespaces untouched
    all_ok = True
    for ns in OTHER_NAMESPACES:
        after_count = stats_after.namespaces.get(ns, type("", (), {"vector_count": 0})()).vector_count
        status = "✓" if after_count == before_counts[ns] else "✗ MISMATCH"
        print(f"  {ns}: {before_counts[ns]} → {after_count} {status}")
        if after_count != before_counts[ns]:
            all_ok = False

    # Confirm unauthorized URLs are gone
    print("\n=== VERIFYING CLEANUP ===")
    for url in UNAUTHORIZED_URLS:
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=url.split("/")[-1].replace("print1", "").replace("-", " ")[:100],
        )
        vec = resp.data[0].embedding
        result = idx.query(
            namespace=NAMESPACE, vector=vec, top_k=10,
            include_metadata=True, filter={"official_url": {"$eq": url}},
        )
        remaining = len(result.matches)
        status = "✓ clean" if remaining == 0 else f"✗ {remaining} REMAINING"
        print(f"  {url.split('show/')[-1]}: {status}")
        if remaining > 0:
            all_ok = False

    if all_ok:
        print("\n✓ Purge complete. All checks passed.")
    else:
        print("\n✗ Some checks failed — review output above.")


if __name__ == "__main__":
    main()
