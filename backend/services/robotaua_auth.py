import requests
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

ROBOTAUA_EMAIL = os.getenv("ROBOTAUA_EMAIL", "")
ROBOTAUA_PASSWORD = os.getenv("ROBOTAUA_PASSWORD", "")

GRAPHQL_URL = "https://dracula.robota.ua/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk",
    "apollographql-client-name": "web-alliance-desktop",
    "apollographql-client-version": "071f324",
    "Content-Type": "application/json",
    "Origin": "https://robota.ua",
    "Referer": "https://robota.ua/",
}

_cached_token: Optional[str] = None
_token_expires_at: float = 0

LOGIN_ENDPOINTS = [
    {
        "url": "https://api.robota.ua/auth/login",
        "json": lambda email, pwd: {"username": email, "password": pwd},
    },
    {
        "url": "https://robota.ua/auth/login",
        "json": lambda email, pwd: {"email": email, "password": pwd},
    },
    {
        "url": "https://api.employer.robota.ua/auth/token",
        "json": lambda email, pwd: {"email": email, "password": pwd},
    },
    {
        "url": "https://employer-api.robota.ua/auth/login",
        "json": lambda email, pwd: {"username": email, "password": pwd, "rememberMe": True},
    },
]


def _extract_token(data: dict) -> Optional[str]:
    return data.get("token") or data.get("accessToken") or data.get("jwt")


def _set_token_expiry(token: str) -> None:
    global _token_expires_at
    import base64
    import json as json_lib
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json_lib.loads(base64.b64decode(payload_b64))
        _token_expires_at = float(payload.get("exp", 0))
    except Exception:
        _token_expires_at = time.time() + 86400


def get_robotaua_token() -> Optional[str]:
    global _cached_token, _token_expires_at

    if not ROBOTAUA_EMAIL or not ROBOTAUA_PASSWORD:
        logger.warning("ROBOTAUA_EMAIL/PASSWORD not configured")
        return None

    if _cached_token and time.time() < (_token_expires_at - 3600):
        logger.debug("Using cached Robota.ua token")
        return _cached_token

    logger.info("Authenticating with Robota.ua...")

    last_resp = None
    req_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Origin": "https://robota.ua",
        "Referer": "https://robota.ua/",
    }

    for endpoint in LOGIN_ENDPOINTS:
        url = endpoint["url"]
        body = endpoint["json"](ROBOTAUA_EMAIL, ROBOTAUA_PASSWORD)

        try:
            resp = requests.post(
                url,
                json=body,
                headers=req_headers,
                timeout=15,
            )
            last_resp = resp
            logger.info(f"Trying: {url} → status {resp.status_code}")

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    continue

                token = _extract_token(data)
                if token:
                    _set_token_expiry(token)
                    _cached_token = token
                    logger.info(f"Robota.ua authentication successful via {url}")
                    return token

        except Exception as e:
            logger.warning(f"Robota.ua endpoint {url} error: {e}")
            continue

    if last_resp is not None:
        logger.error(f"Robota.ua login failed. Last status: {last_resp.status_code}")
        try:
            logger.error(f"Last response body: {last_resp.text[:200]}")
        except Exception:
            pass
    else:
        logger.error("Robota.ua login failed - no endpoints responded")

    return None


def get_graphql_headers(token: str) -> dict:
    headers = HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return headers
