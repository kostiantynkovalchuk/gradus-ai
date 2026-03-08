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


def get_robotaua_token() -> Optional[str]:
    global _cached_token, _token_expires_at

    if not ROBOTAUA_EMAIL or not ROBOTAUA_PASSWORD:
        logger.warning("ROBOTAUA_EMAIL/PASSWORD not configured")
        return None

    if _cached_token and time.time() < (_token_expires_at - 3600):
        logger.debug("Using cached Robota.ua token")
        return _cached_token

    logger.info("Authenticating with Robota.ua...")

    try:
        login_resp = requests.post(
            "https://employer-api.robota.ua/auth/login",
            json={
                "username": ROBOTAUA_EMAIL,
                "password": ROBOTAUA_PASSWORD,
                "rememberMe": True,
            },
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Content-Type": "application/json",
                "Origin": "https://robota.ua",
                "Referer": "https://robota.ua/",
            },
            timeout=15,
        )

        if login_resp.status_code == 200:
            data = login_resp.json()
            token = data.get("token") or data.get("accessToken")

            if token:
                import base64
                import json as json_lib
                try:
                    payload_b64 = token.split(".")[1]
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = json_lib.loads(base64.b64decode(payload_b64))
                    _token_expires_at = float(payload.get("exp", 0))
                except Exception:
                    _token_expires_at = time.time() + 86400

                _cached_token = token
                logger.info("Robota.ua authentication successful")
                return token

        logger.warning(
            f"Primary login failed ({login_resp.status_code}), trying alternative..."
        )

        alt_resp = requests.post(
            "https://robota.ua/api/auth/login",
            json={
                "email": ROBOTAUA_EMAIL,
                "password": ROBOTAUA_PASSWORD,
            },
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Content-Type": "application/json",
            },
            timeout=15,
        )

        if alt_resp.status_code == 200:
            data = alt_resp.json()
            token = data.get("token") or data.get("accessToken") or data.get("jwt")
            if token:
                _cached_token = token
                _token_expires_at = time.time() + 86400
                logger.info("Robota.ua authentication successful (alt endpoint)")
                return token

        logger.error(f"Robota.ua login failed. Status: {alt_resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"Robota.ua auth error: {e}")
        return None


def get_graphql_headers(token: str) -> dict:
    headers = HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return headers
