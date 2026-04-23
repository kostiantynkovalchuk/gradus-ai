"""
Pinecone legal corpus management for Solomon Contracts.
Namespace: 'solomon-contracts-corpus'
Model: text-embedding-3-small (1536-dim, matches existing index)
"""
import hashlib
import json
import logging
import os
import re
import time
from typing import Optional

import openai

logger = logging.getLogger(__name__)

CORPUS_NS = "solomon-contracts-corpus"
FINDINGS_NS = "solomon-contracts-findings"
EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX_TOKENS = 800


def _pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    return pc.Index(os.getenv("PINECONE_INDEX_NAME", "gradus-media"))


def _embed(text: str) -> list[float]:
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.embeddings.create(model=EMBED_MODEL, input=text[:8192])
    return resp.data[0].embedding


def _chunk_by_article(text: str) -> list[str]:
    """Split Ukrainian law text by Стаття N boundaries."""
    parts = re.split(r"(?m)(?=^Стаття\s+\d+)", text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        words = part.split()
        if len(words) <= CHUNK_MAX_TOKENS:
            chunks.append(part)
        else:
            for i in range(0, len(words), CHUNK_MAX_TOKENS):
                chunks.append(" ".join(words[i:i + CHUNK_MAX_TOKENS]))
    return chunks


def _chunk_incoterms(text: str) -> list[str]:
    """Split INCOTERMS PDF by rule sections (EXW, FCA, CPT, etc.)."""
    rules = ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]
    pattern = r"(?m)(?=" + "|".join(rf"\b{r}\b" for r in rules) + r")"
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p.strip()]


def retrieve_similar(query: str, top_k: int = 5, namespace: str = CORPUS_NS) -> list[dict]:
    """Embed query and fetch top_k chunks from the corpus namespace."""
    try:
        idx = _pinecone_index()
        vec = _embed(query)
        result = idx.query(vector=vec, top_k=top_k, namespace=namespace, include_metadata=True)
        return [
            {
                "id": m.id,
                "score": m.score,
                "source_title": m.metadata.get("source_title", ""),
                "article_ref": m.metadata.get("article_ref", ""),
                "official_url": m.metadata.get("official_url", ""),
                "chunk_text": m.metadata.get("chunk_text", ""),
            }
            for m in result.matches
        ]
    except Exception as e:
        logger.error(f"[SolCon] Pinecone retrieve failed: {e}")
        return []


def store_finding_vector(finding_id: int, short_note: str, metadata: dict):
    """Embed a finding and upsert into the findings namespace."""
    try:
        idx = _pinecone_index()
        vec = _embed(short_note)
        idx.upsert(
            vectors=[{
                "id": f"finding_{finding_id}",
                "values": vec,
                "metadata": {"finding_id": finding_id, **metadata},
            }],
            namespace=FINDINGS_NS,
        )
    except Exception as e:
        logger.error(f"[SolCon] Findings vector upsert failed: {e}")


def ingest_law_text(
    source_id: int, title: str, official_url: str, text: str, source_type: str = "ukr_law",
) -> int:
    """Chunk a law text and upsert all chunks to Pinecone. Returns chunk count."""
    idx = _pinecone_index()
    chunks = _chunk_by_article(text)
    vectors = []
    for i, chunk in enumerate(chunks):
        article_match = re.match(r"^Стаття\s+(\d+)", chunk)
        article_ref = f"Ст. {article_match.group(1)}" if article_match else f"chunk_{i}"
        vec_id = f"corpus_{source_id}_{i}"
        vec = _embed(chunk)
        vectors.append({
            "id": vec_id,
            "values": vec,
            "metadata": {
                "source_id": source_id,
                "source_type": source_type,
                "source_title": title,
                "article_ref": article_ref,
                "official_url": official_url,
                "chunk_text": chunk[:1000],
            },
        })
        if len(vectors) >= 50:
            idx.upsert(vectors=vectors, namespace=CORPUS_NS)
            vectors = []
    if vectors:
        idx.upsert(vectors=vectors, namespace=CORPUS_NS)
    return len(chunks)


def ingest_incoterms_pdf(source_id: int, pdf_bytes: bytes) -> int:
    """Extract and ingest INCOTERMS 2020 PDF into corpus."""
    import pdfplumber, io
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    full_text = "\n\n".join(pages)
    chunks = _chunk_incoterms(full_text)
    idx = _pinecone_index()
    vectors = []
    rules = ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]
    for i, chunk in enumerate(chunks):
        rule_match = next((r for r in rules if re.search(rf"\b{r}\b", chunk[:50])), None)
        article_ref = f"INCOTERMS {rule_match}" if rule_match else f"INCOTERMS chunk_{i}"
        vec = _embed(chunk)
        vectors.append({
            "id": f"incoterms_{source_id}_{i}",
            "values": vec,
            "metadata": {
                "source_id": source_id,
                "source_type": "incoterms_2020",
                "source_title": "INCOTERMS 2020",
                "article_ref": article_ref,
                "official_url": "",
                "chunk_text": chunk[:1000],
            },
        })
        if len(vectors) >= 50:
            idx.upsert(vectors=vectors, namespace=CORPUS_NS)
            vectors = []
    if vectors:
        idx.upsert(vectors=vectors, namespace=CORPUS_NS)
    return len(chunks)


def rebuild_corpus_namespace(on_progress=None) -> int:
    """
    Delete and rebuild the entire corpus namespace from solcon_corpus_sources.
    Laws are fetched from zakon.rada.gov.ua with redirect-following.
    INCOTERMS are skipped here — upload separately via the incoterms endpoint.
    on_progress: optional callable(str) for progress reporting.
    Returns total chunks ingested.
    """
    from . import db as solcon_db
    import requests

    def _prog(msg: str):
        logger.info(f"[SolCon] {msg}")
        if on_progress:
            on_progress(msg)

    idx = _pinecone_index()
    try:
        idx.delete(delete_all=True, namespace=CORPUS_NS)
        _prog("Corpus namespace cleared")
    except Exception as e:
        _prog(f"Namespace clear warning: {e}")

    sources = solcon_db.fetchall(
        "SELECT id, title, official_url, source_type FROM solcon_corpus_sources"
    )
    total = 0
    for src in sources:
        try:
            if src["source_type"] == "incoterms_2020":
                _prog(f"Skipping INCOTERMS (upload separately): {src['title']}")
                continue
            _prog(f"Fetching: {src['title']} …")
            resp = requests.get(
                src["official_url"],
                timeout=60,
                headers={"Accept": "text/html", "User-Agent": "SolomonContracts/1.0"},
                allow_redirects=True,
            )
            if resp.status_code != 200:
                _prog(f"HTTP {resp.status_code} for {src['title']} — skipping")
                continue
            # Record canonical URL if redirect occurred
            if resp.url != src["official_url"]:
                solcon_db.execute(
                    "UPDATE solcon_corpus_sources SET official_url=%s WHERE id=%s",
                    (resp.url, src["id"]),
                )
            text = _strip_html(resp.text)
            count = ingest_law_text(src["id"], src["title"], resp.url, text, src["source_type"])
            solcon_db.execute(
                "UPDATE solcon_corpus_sources SET chunk_count=%s, last_ingested_at=NOW() WHERE id=%s",
                (count, src["id"]),
            )
            total += count
            _prog(f"Ingested {count} chunks: {src['title']}")
        except Exception as e:
            _prog(f"Failed to ingest {src['title']}: {e}")
    return total


# ─── §7 Sanity queries (auto-run after rebuild) ───────────────────────────────

SANITY_QUERIES = [
    ("штраф за порушення умов поставки товару постачальником", "penalty_check"),
    ("повернення товару покупцем права споживача", "returns_check"),
    ("розірвання договору постачання дострокове одностороннє", "termination_check"),
    ("відповідальність за якість безпечність харчових продуктів", "quality_check"),
    ("INCOTERMS DDP зобов'язання постачальника умови доставки", "incoterms_check"),
]


def run_sanity_queries() -> dict:
    """
    Run 5 representative queries against the corpus and return plausibility scores.
    A query is considered 'passed' if: hit_count >= 3 AND top_score >= 0.35.
    Overall sanity passes when at least 4 of 5 queries pass.
    """
    results: dict = {}
    for query, name in SANITY_QUERIES:
        hits = retrieve_similar(query, top_k=5)
        top_score = hits[0]["score"] if hits else 0.0
        hit_count = len(hits)
        passed = hit_count >= 3 and top_score >= 0.35
        results[name] = {
            "query": query,
            "hit_count": hit_count,
            "top_score": round(top_score, 4),
            "top_source": hits[0]["source_title"] if hits else None,
            "top_article": hits[0]["article_ref"] if hits else None,
            "passed": passed,
        }
    passing = sum(1 for v in results.values() if v.get("passed", False))
    results["_summary"] = {
        "passing": passing,
        "total": len(SANITY_QUERIES),
        "ok": passing >= 4,
    }
    logger.info(f"[SolCon] Sanity queries: {passing}/{len(SANITY_QUERIES)} passed")
    return results


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
