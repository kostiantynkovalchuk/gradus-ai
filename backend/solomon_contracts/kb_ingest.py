"""
Phase 4 — Ingest missing approved sources into solomon-contracts-corpus.

Each law is fetched from zakon.rada.gov.ua (/print1 endpoint for full text),
chunked by article, embedded with text-embedding-3-small, and upserted to
Pinecone.  Edition metadata is stored in solomon_kb_sources.

Usage:
    from solomon_contracts.kb_ingest import ingest_law
    result = ingest_law("3817-20")
    # → {"chunks_added": 45, "edition_date": date(2024,1,1), "edition_basis": "..."}
"""
import logging
import os
import re
import time
from datetime import date
from typing import Optional

import openai
import requests
from bs4 import BeautifulSoup

from . import db as solcon_db
from .corpus import _pinecone_index

logger = logging.getLogger(__name__)

NAMESPACE = "solomon-contracts-corpus"
assert NAMESPACE == "solomon-contracts-corpus", "Wrong namespace — would corrupt other products"

EMBED_MODEL = "text-embedding-3-small"
# OpenAI limits: 8192 tokens/input for text-embedding-3-small.
# Ukrainian (Cyrillic) text is ~1 character per token in cl100k_base.
# Cap at 6000 chars to stay safely under the 8192 token limit.
_MAX_CHUNK_CHARS = 6_000
# Batch size: 6000 chars * 80 = 480k chars ≈ 480k tokens → still over 300k limit.
# Use 40 texts per batch to stay safely under 300k tokens/request.
_EMBED_BATCH = 40

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# zakon.rada.gov.ua canonical page, after HTML stripping, renders as:
#   "Редакція від 01.02.2026 , підстава - 4671-IX"
# BeautifulSoup get_text(separator=' ') inserts a space before the comma.
# Also handle both "підстава" and "підстави".
_CUR_EDITION_RE = re.compile(
    r"Редакція від (\d{2}\.\d{2}\.\d{4})\s*,\s*підстав[аи]\s*[-–-]\s*(\S+)"
)
_NEXT_EVENT_RE = re.compile(
    r"(?:Остання подія|наступна редакція).*?підстав[аи]\s*[-–-]\s*(\S+)", re.DOTALL
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SolomonContracts/1.0)",
    "Accept": "text/html",
}


# ─── Public API ───────────────────────────────────────────────────────────────

def ingest_law(law_code: str) -> dict:
    """
    Fetch a law from zakon.rada.gov.ua (/print1), parse current edition,
    chunk by article, embed, upsert to Pinecone with full metadata, and
    update solomon_kb_sources.

    Returns: {"chunks_added": int, "edition_date": date|None, "edition_basis": str|None}
    Raises: ValueError if law_code not in registry or status != 'active'
    """
    source = solcon_db.fetchone(
        "SELECT * FROM solomon_kb_sources WHERE law_code = %s", (law_code,)
    )
    if not source:
        raise ValueError(f"Law {law_code!r} not in approved KB registry")
    if source["status"] != "active":
        raise ValueError(
            f"Law {law_code!r} has status '{source['status']}', must be 'active'"
        )

    canonical_url = source["canonical_url"]
    if not canonical_url:
        raise ValueError(f"Law {law_code!r} has no canonical_url — cannot ingest")

    logger.info(f"[KBIngest] Starting ingest for {law_code} from {canonical_url}")

    # Fetch 1: canonical page → edition header only.
    # The canonical page is a JS-SPA shell with no law body text, but it DOES
    # carry the "Редакція від DD.MM.YYYY, підстава - XXXX" header in plain HTML.
    # _fetch_current_edition follows any "Це не поточна редакція" redirect so
    # final_canonical_url is always the URL of the CURRENT edition.
    canonical_html, final_canonical_url = _fetch_current_edition(canonical_url, max_hops=3)
    edition_date, edition_basis, next_basis, next_date = _parse_edition_header(canonical_html)
    logger.info(f"[KBIngest] {law_code}: edition={edition_date}, basis={edition_basis}")

    # Fetch 2: /print1 of the SAME current edition → full law body for chunking.
    # Derive print_url from final_canonical_url (not source.canonical_url) so
    # both edition metadata and chunk content always describe the same edition.
    print_url = final_canonical_url.rstrip("/") + "/print1"
    html = _fetch_print1(print_url)

    chunks = _chunk_by_article(
        html,
        source_id=source["id"],
        source_title=source["law_name"],
        official_url=print_url,
    )

    if not chunks:
        logger.warning(f"[KBIngest] {law_code}: no article chunks — falling back to paragraph chunking")
        chunks = _chunk_by_paragraph(
            html,
            source_id=source["id"],
            source_title=source["law_name"],
            official_url=print_url,
        )

    if not chunks:
        raise RuntimeError(f"[KBIngest] {law_code}: produced 0 chunks — aborting to avoid empty upsert")

    logger.info(f"[KBIngest] {law_code}: embedding {len(chunks)} chunks")

    texts = [c["chunk_text"] for c in chunks]
    embeddings = _batch_embed(texts)

    idx = _pinecone_index()
    _delete_existing_chunks(source["id"], idx)

    def _safe_meta(chunk: dict, ed_date) -> dict:
        """Build Pinecone metadata — omit any None values (Pinecone rejects null)."""
        meta = {k: v for k, v in chunk.items() if k != "chunk_text" and v is not None}
        meta["chunk_text"] = chunk["chunk_text"][:1000]
        meta["kb_source_id"] = source["id"]
        if ed_date is not None:
            meta["current_edition_date"] = ed_date.isoformat()
        return meta

    vectors = [
        {
            "id": f"corpus_{source['id']}_{i}",
            "values": emb,
            "metadata": _safe_meta(chunks[i], edition_date),
        }
        for i, emb in enumerate(embeddings)
    ]

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        idx.upsert(vectors=vectors[i : i + batch_size], namespace=NAMESPACE)

    solcon_db.execute(
        """UPDATE solomon_kb_sources
           SET current_edition_date        = %s,
               current_edition_basis       = %s,
               next_edition_basis          = %s,
               next_edition_date_estimated = %s,
               last_verified_at            = NOW(),
               updated_at                  = NOW()
           WHERE id = %s""",
        (edition_date, edition_basis, next_basis, next_date, source["id"]),
    )

    logger.info(f"[KBIngest] {law_code}: upserted {len(vectors)} chunks ✓")
    return {
        "chunks_added": len(vectors),
        "edition_date": edition_date,
        "edition_basis": edition_basis,
    }


# ─── Embedding ────────────────────────────────────────────────────────────────

def _batch_embed(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using text-embedding-3-small.
    - Each text is truncated to _MAX_CHUNK_CHARS chars before sending.
    - Requests are batched in groups of _EMBED_BATCH to stay under the
      300k-token-per-request and 8192-token-per-input OpenAI limits.
    Returns a list of embedding vectors in the same order as input.
    """
    if not texts:
        return []
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    all_embeddings: list[list[float]] = []
    safe_texts = [t[:_MAX_CHUNK_CHARS] for t in texts]
    for batch_start in range(0, len(safe_texts), _EMBED_BATCH):
        batch = safe_texts[batch_start : batch_start + _EMBED_BATCH]
        for attempt in range(3):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
                # resp.data is ordered by index, same as input
                batch_vecs = [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
                all_embeddings.extend(batch_vecs)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                logger.warning(f"[KBIngest] Embed batch {batch_start} attempt {attempt+1} failed: {e} — retry")
                time.sleep(2 ** attempt)
    return all_embeddings


# ─── Fetch helpers ────────────────────────────────────────────────────────────

def _fetch_current_edition(canonical_url: str, max_hops: int = 3):
    """
    Fetch the CANONICAL zakon.rada.gov.ua page, following the
    'Це не поточна редакція документу' redirect up to max_hops times.

    Returns (html: str, final_url: str) for the CURRENT edition's canonical page.
    The returned html is the raw HTML of the canonical page (not /print1) and is
    intended solely for edition-header parsing via _parse_edition_header().
    """
    url = canonical_url
    for _ in range(max_hops):
        resp = requests.get(url, headers=_HEADERS, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # If the page warns "not the current edition", follow the link
        if soup.find(string=re.compile(r"Це не поточна редакція")):
            link = soup.find("a", string=re.compile(r"Перейти до поточної"))
            if link and link.get("href"):
                href = link["href"]
                if href.startswith("/"):
                    href = "https://zakon.rada.gov.ua" + href
                url = href
                continue
        return resp.text, resp.url
    # Exhausted hops — return whatever we have
    return resp.text, resp.url


def _fetch_print1(print_url: str, retries: int = 3) -> str:
    """
    Fetch a zakon.rada.gov.ua /print1 page.  Uses a single User-Agent that
    the site accepts, with exponential back-off between retries.
    Returns the HTML text.  Raises RuntimeError on all failures.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(print_url, headers=_HEADERS, timeout=60, allow_redirects=True)
            resp.raise_for_status()
            if len(resp.text) < 5000:
                raise RuntimeError(f"Response too small ({len(resp.text)} bytes) — likely blocked")
            return resp.text
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Failed to fetch {print_url} after {retries} attempts: {e}") from e
            wait = 2 ** attempt
            logger.warning(f"[KBIngest] Attempt {attempt+1} failed for {print_url}: {e} — retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Unreachable: {print_url}")


def _parse_edition_header(html: str):
    """
    Parse edition metadata from a zakon.rada.gov.ua CANONICAL page.

    The canonical page wraps the date and basis in HTML tags:
        <b>Редакція</b> від <span class="dat0"><b>01.02.2026</b></span>,
        підстава - <a href="...">4671-IX</a>

    After BeautifulSoup stripping with separator=' ' this becomes:
        "Редакція від 01.02.2026 , підстава - 4671-IX"

    Laws that have never been amended carry no "Редакція від" line at all —
    the function returns (None, None, None, None) without raising in that case.

    Returns (current_date, current_basis, next_basis, next_date_or_None).
    """
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(separator=" "))
    m_cur = _CUR_EDITION_RE.search(text)
    m_next = _NEXT_EVENT_RE.search(text)
    cur_date = _parse_date_dmy(m_cur.group(1)) if m_cur else None
    cur_basis = m_cur.group(2).rstrip(".,;)") if m_cur else None
    next_basis = m_next.group(1).rstrip(".,;)") if m_next else None
    return cur_date, cur_basis, next_basis, None


def _parse_date_dmy(s: str) -> Optional[date]:
    m = _DATE_RE.match(s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# ─── Pinecone cleanup ─────────────────────────────────────────────────────────

def _delete_existing_chunks(source_id: int, idx):
    """Delete all existing Pinecone vectors for this source by ID pattern."""
    assert NAMESPACE == "solomon-contracts-corpus"
    ids_to_delete = []
    for chunk_i in range(5000):
        ids_to_delete.append(f"corpus_{source_id}_{chunk_i}")
        if len(ids_to_delete) >= 100:
            try:
                idx.delete(ids=ids_to_delete, namespace=NAMESPACE)
            except Exception:
                pass
            ids_to_delete = []
    if ids_to_delete:
        try:
            idx.delete(ids=ids_to_delete, namespace=NAMESPACE)
        except Exception:
            pass


# ─── Chunking ─────────────────────────────────────────────────────────────────

def _clean_html_to_text(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_by_article(
    html: str,
    source_id: int,
    source_title: str,
    official_url: str,
) -> list[dict]:
    """
    Split law text into per-article chunks.
    Returns [] if fewer than 3 articles found (triggers paragraph fallback).
    """
    text = _clean_html_to_text(html)
    article_re = re.compile(r"(?m)^(Стаття\s+(\d[\d\-]*\w*)\.)")
    positions = [(m.start(), m.group(2)) for m in article_re.finditer(text)]

    if len(positions) < 3:
        return []

    chunks = []
    for i, (start, art_num) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk_text = text[start:end].strip()
        if len(chunk_text) < 20:
            continue
        if len(chunk_text) > _MAX_CHUNK_CHARS:
            for part_i, sub_chunk in enumerate(_split_long_text(chunk_text, max_chars=_MAX_CHUNK_CHARS - 500)):
                chunks.append({
                    "article_ref": f"Ст. {art_num}" + (f" (ч.{part_i+1})" if part_i else ""),
                    "chunk_text": sub_chunk,
                    "source_id": source_id,
                    "source_title": source_title,
                    "official_url": official_url,
                    "source_type": "ukr_law",
                })
        else:
            chunks.append({
                "article_ref": f"Ст. {art_num}",
                "chunk_text": chunk_text,
                "source_id": source_id,
                "source_title": source_title,
                "official_url": official_url,
                "source_type": "ukr_law",
            })
    return chunks


def _chunk_by_paragraph(
    html: str,
    source_id: int,
    source_title: str,
    official_url: str,
    max_chars: int = 2000,
) -> list[dict]:
    """Fallback: split by paragraphs of ~max_chars each."""
    text = _clean_html_to_text(html)
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 30]
    if not paras:
        return []
    chunks = []
    current, idx_i = [], 0
    current_len = 0
    for para in paras:
        if current_len + len(para) > max_chars and current:
            chunks.append({
                "article_ref": f"chunk_{idx_i}",
                "chunk_text": "\n\n".join(current),
                "source_id": source_id,
                "source_title": source_title,
                "official_url": official_url,
                "source_type": "ukr_law",
            })
            idx_i += 1
            current, current_len = [], 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append({
            "article_ref": f"chunk_{idx_i}",
            "chunk_text": "\n\n".join(current),
            "source_id": source_id,
            "source_title": source_title,
            "official_url": official_url,
            "source_type": "ukr_law",
        })
    return chunks


def _split_long_text(text: str, max_chars: int = 3500) -> list[str]:
    """Split a long article into sub-chunks at sentence boundaries."""
    parts, current = [], []
    current_len = 0
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current_len + len(sentence) > max_chars and current:
            parts.append(" ".join(current))
            current, current_len = [], 0
        current.append(sentence)
        current_len += len(sentence)
    if current:
        parts.append(" ".join(current))
    return parts or [text[:max_chars]]
