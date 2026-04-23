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


def _strip_preamble(text: str) -> str:
    """
    Discard the preamble (ministry header, promulgation history, etc.) from a
    zakon.rada.gov.ua law text.  Searches for the first structural marker and
    returns the text from that point onward.

    Handled variants (all observed on zakon.rada.gov.ua):
      РОЗДІЛ I. ЗАГАЛЬНІ ПОЛОЖЕННЯ
      Розділ I
      Розділ 1.
      Стаття 1.
      Стаття 1 (space delimiter)
      Стаття 1\\n (newline delimiter)
      СТАТТЯ 1.
      РОЗДІЛ I. ЗАГАЛЬНІ ПОЛОЖЕННЯ
      Глава 1.   ← sector-specific laws

    Negative lookaheads prevent false matches inside:
      Розділ 10   Стаття 10   Стаття 100   Розділ II (Roman II)
    """
    pattern = re.compile(
        r"(?m)^("
        r"(?:РОЗДІЛ|Розділ)\s+(?:I|1)(?![0-9IVX])[.\s]"  # Розділ I / Розділ 1
        r"|(?:СТАТТЯ|Стаття)\s+1(?!\d)[.\s]"               # Стаття 1. / Стаття 1\n
        r"|(?:ГЛАВА|Глава)\s+1(?!\d)[.\s]"                  # Глава 1
        r")"
    )
    m = pattern.search(text)
    return text[m.start():] if m else text


def _group_into_chunks(parts: list, header: str) -> list:
    """Pack sub-parts into ≤ CHUNK_MAX_TOKENS-word chunks, prepending header."""
    chunks = []
    current: list = []
    current_words = 0
    for part in parts:
        w = len(part.split())
        if current_words + w > CHUNK_MAX_TOKENS and current:
            chunks.append(header + "\n" + "\n".join(current))
            current = [part]
            current_words = w
        else:
            current.append(part)
            current_words += w
    if current:
        chunks.append(header + "\n" + "\n".join(current))
    return chunks


def _split_oversized_article(article_text: str) -> list:
    """
    Split an article that exceeds CHUNK_MAX_TOKENS words.
    Priority order — stops at the first strategy that produces >1 part:
      1. Numbered sub-paragraph markers  (e.g. "201.1.", "14.1.54.")
      2. Blank-line paragraph boundaries
      3. Word-count split (last resort) — article header prepended to every chunk
    """
    header_line, _, body = article_text.partition("\n")
    header = header_line.strip()
    body = body.strip()

    # 1. Sub-paragraph markers: lines starting with N.N. or N.N.N.
    sub_pat = re.compile(r"(?m)(?=^\d+\.\d+(?:\.\d+)*\b)")
    sub_parts = [p.strip() for p in sub_pat.split(body) if p.strip()]
    if len(sub_parts) > 1:
        return _group_into_chunks(sub_parts, header)

    # 2. Blank-line splits
    blank_parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(blank_parts) > 1:
        return _group_into_chunks(blank_parts, header)

    # 3. Word-count — prepend header to continuation chunks
    words = article_text.split()
    h_words = header.split()
    result = []
    for i in range(0, len(words), CHUNK_MAX_TOKENS):
        chunk = words[i:i + CHUNK_MAX_TOKENS]
        if i > 0:
            chunk = h_words + ["…"] + chunk
        result.append(" ".join(chunk))
    return result


def _filter_sub_articles(article_text: str, wanted: set) -> list:
    """
    Split an article on sub-article boundary markers (e.g. "14.1.54 ")
    and keep only those whose ID string is in 'wanted'.
    Each kept sub-article is returned as its own chunk with the article header.
    Falls back to the whole article text if no sub-article markers are found.
    """
    header_line, _, body = article_text.partition("\n")
    header = header_line.strip()

    # Find all sub-article start positions and their IDs
    matches = list(re.finditer(r"(?m)^(\d+\.\d+(?:\.\d+)*)\b", body))
    if not matches:
        return [article_text]  # no sub-article structure — keep whole

    positions = [(m.start(), m.group(1)) for m in matches]
    positions.append((len(body), None))  # sentinel

    chunks = []
    for i, (start, sub_id) in enumerate(positions[:-1]):
        if sub_id not in wanted:
            continue
        end = positions[i + 1][0]
        sub_text = body[start:end].strip()
        if sub_text:
            chunks.append(header + "\n" + sub_text)

    return chunks if chunks else [article_text]


def _chunk_by_article(
    text: str,
    article_filter=None,
    sub_article_filter=None,
) -> list:
    """
    Split Ukrainian law text by 'Стаття N' boundaries.

    article_filter:     list of (from_art, to_art) int tuples → keep only those
                        articles whose number falls in at least one range.
                        None = keep all articles.

    sub_article_filter: dict mapping art_num (int) → set/list of sub-article ID
                        strings (e.g. {14: {"14.1.54", "14.1.71", …}}).
                        When set for an article, that article is split at
                        sub-article boundaries and only matching sub-articles
                        are kept as individual chunks.
    """
    parts = re.split(r"(?m)(?=^Стаття\s+\d+)", text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        m = re.match(r"^Стаття\s+(\d+)", part)
        art_num = int(m.group(1)) if m else None

        # ── Article-range filter ──────────────────────────────────────────────
        if article_filter is not None and art_num is not None:
            if not any(lo <= art_num <= hi for lo, hi in article_filter):
                continue

        # ── Sub-article filter (e.g. Art 14 of the Tax Code) ─────────────────
        if sub_article_filter and art_num in sub_article_filter:
            wanted = set(sub_article_filter[art_num])
            chunks.extend(_filter_sub_articles(part, wanted))
            continue

        # ── Standard: whole article, split if oversized ───────────────────────
        if len(part.split()) <= CHUNK_MAX_TOKENS:
            chunks.append(part)
        else:
            chunks.extend(_split_oversized_article(part))

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
    source_id: int,
    title: str,
    official_url: str,
    text: str,
    source_type: str = "ukr_law",
    article_filter=None,
    sub_article_filter=None,
) -> int:
    """Chunk a law text and upsert all chunks to Pinecone. Returns chunk count."""
    idx = _pinecone_index()
    chunks = _chunk_by_article(
        text,
        article_filter=article_filter,
        sub_article_filter=sub_article_filter,
    )
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


def rebuild_corpus_namespace(on_progress=None, law_filters: dict = None) -> int:
    """
    Delete and rebuild the entire corpus namespace from solcon_corpus_sources.
    Laws are fetched from zakon.rada.gov.ua with redirect-following.
    INCOTERMS are skipped here — upload separately via the incoterms endpoint.

    on_progress:  optional callable(str) for job progress reporting.
    law_filters:  dict keyed by official_url OR title →
                  {"article_filter": [...], "sub_article_filter": {...}}
                  Built from LAW_SOURCES by the router and passed in to avoid
                  circular imports.

    Returns total chunks ingested.
    """
    from . import db as solcon_db
    import requests

    def _prog(msg: str):
        logger.info(f"[SolCon] {msg}")
        if on_progress:
            on_progress(msg)

    def _get_filters(url: str, title: str) -> dict:
        """Look up article/sub_article filters from law_filters by URL then title."""
        if not law_filters:
            return {}
        return law_filters.get(url) or law_filters.get(title) or {}

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
            # zakon.rada.gov.ua base URLs return a JS-SPA shell (~5KB).
            # /print1 serves the full plain-HTML text (~150-400KB).
            base_url = src["official_url"].rstrip("/")
            fetch_url = (
                base_url + "/print1"
                if "zakon.rada.gov.ua" in base_url
                else base_url
            )
            resp = requests.get(
                fetch_url,
                timeout=90,
                headers={
                    "Accept": "text/html",
                    "User-Agent": "Mozilla/5.0 (compatible; SolomonContracts/1.0)",
                },
                allow_redirects=True,
            )
            if resp.status_code != 200:
                _prog(f"HTTP {resp.status_code} for {src['title']} — skipping")
                continue
            # Store canonical base URL (without /print1) in DB
            canonical = resp.url.replace("/print1", "").rstrip("/")
            if canonical != base_url:
                solcon_db.execute(
                    "UPDATE solcon_corpus_sources SET official_url=%s WHERE id=%s",
                    (canonical, src["id"]),
                )
            raw = _strip_html(resp.text)
            stripped = _strip_preamble(raw)
            filt = _get_filters(src["official_url"], src["title"])
            count = ingest_law_text(
                src["id"], src["title"], resp.url, stripped, src["source_type"],
                article_filter=filt.get("article_filter"),
                sub_article_filter=filt.get("sub_article_filter"),
            )
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
    """
    Convert zakon.rada.gov.ua /print1 HTML to plain text preserving line
    structure so that 'Стаття N' appears at the start of a line (required by
    _chunk_by_article's (?m)^Стаття split).

    Block-level tags (p, div, br, h1-h6, li, tr) → newline.
    All remaining tags → stripped.
    """
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    # Block-level tags → newline so article headers start on their own line
    text = re.sub(
        r"</?(p|div|br|h[1-6]|li|tr|td|th|section|article)\b[^>]*>",
        "\n", text, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)       # strip remaining inline tags
    text = re.sub(r"[ \t]+", " ", text)        # collapse horizontal whitespace
    text = re.sub(r" *\n *", "\n", text)       # trim spaces around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)     # collapse excess blank lines
    return text.strip()
