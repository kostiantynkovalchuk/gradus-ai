"""
Cloudflare-bypass HTTP client for Robota.ua employer API.
=========================================================
Three-layer defence (per spec):
  A. Browser-realistic headers  — always applied
  B. curl_cffi Chrome TLS impersonation — primary bypass
  C. Retry on 403 with 5s / 10s backoff — resilience

Usage (drop-in replacement for httpx.AsyncClient):
    from services.robotaua_client import cf_client
    async with cf_client(timeout=20) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp = await client.get(url, headers=headers)

Also available as standalone helpers:
    from services.robotaua_client import cf_get, cf_post
"""

import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# ── Option A: browser-realistic headers ───────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://employer.robota.ua",
    "Referer": "https://employer.robota.ua/",
    "sec-ch-ua": '"Chromium";v="123", "Not:A-Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

# ── Option C: retry settings ───────────────────────────────────────────────
_RETRY_DELAYS = [5, 10]  # seconds; 0 = first attempt (no wait)


class _CfSession:
    """
    Thin wrapper around curl_cffi (or httpx) that:
      1. Merges BROWSER_HEADERS with caller-supplied headers
      2. Retries on 403 with _RETRY_DELAYS backoff
    API mirrors httpx.AsyncClient: .get(url, headers=..., **kw)
                                   .post(url, headers=..., **kw)
    """

    def __init__(self, session, timeout: int):
        self._session = session
        self._timeout = timeout

    def _merge(self, extra: dict | None) -> dict:
        merged = dict(BROWSER_HEADERS)
        if extra:
            merged.update(extra)
        return merged

    async def _req(self, method: str, url: str, headers: dict | None, **kwargs):
        merged = self._merge(headers)
        # _cf_no_retry=True skips retry — use for endpoints with their own fallback logic
        no_retry = kwargs.pop("_cf_no_retry", False)
        delays = [0] if no_retry else ([0] + _RETRY_DELAYS)
        # Ensure timeout is passed if the underlying client supports it
        if "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout

        last_resp = None
        for attempt, delay in enumerate(delays):
            if delay:
                logger.warning(
                    f"[RobotaUA-Client] {method} 403 on attempt {attempt}, "
                    f"retrying in {delay}s... ({url})"
                )
                await asyncio.sleep(delay)
            try:
                fn = getattr(self._session, method.lower())
                resp = await fn(url, headers=merged, **kwargs)
                last_resp = resp
                if resp.status_code != 403:
                    return resp
                logger.warning(
                    f"[RobotaUA-Client] {method} → 403 "
                    f"(attempt {attempt + 1}/{len(_RETRY_DELAYS) + 1}): {url}"
                )
            except Exception as e:
                logger.error(f"[RobotaUA-Client] {method} error (attempt {attempt + 1}): {e}")

        logger.error(f"[RobotaUA-Client] {method} {url} — all retries exhausted, last status={getattr(last_resp, 'status_code', 'N/A')}")
        return last_resp

    async def get(self, url: str, headers: dict | None = None, **kwargs):
        return await self._req("GET", url, headers, **kwargs)

    async def post(self, url: str, headers: dict | None = None, **kwargs):
        return await self._req("POST", url, headers, **kwargs)


@asynccontextmanager
async def cf_client(timeout: int = 20):
    """
    Async context manager: yields a _CfSession using curl_cffi Chrome
    impersonation (Option B), falling back to httpx if not available.

    Usage:
        async with cf_client(timeout=20) as client:
            resp = await client.post(url, headers=auth_headers, json=body)
    """
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome") as session:
            yield _CfSession(session, timeout=timeout)
        return
    except ImportError:
        logger.warning("[RobotaUA-Client] curl_cffi not installed — falling back to httpx")
    except Exception as e:
        logger.warning(f"[RobotaUA-Client] curl_cffi session error: {e} — falling back to httpx")

    import httpx
    async with httpx.AsyncClient(timeout=timeout) as session:
        yield _CfSession(session, timeout=timeout)


# ── Standalone helpers for simple one-off requests ─────────────────────────

async def cf_get(url: str, headers: dict | None = None, timeout: int = 20):
    """One-off GET with Cloudflare bypass."""
    async with cf_client(timeout=timeout) as client:
        return await client.get(url, headers=headers)


async def cf_post(url: str, headers: dict | None = None, json_body=None, timeout: int = 20):
    """One-off POST with Cloudflare bypass."""
    async with cf_client(timeout=timeout) as client:
        return await client.post(url, headers=headers, json=json_body)
