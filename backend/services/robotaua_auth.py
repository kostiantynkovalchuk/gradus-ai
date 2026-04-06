import os
import time
import logging

from services.robotaua_client import cf_client

logger = logging.getLogger(__name__)

_token_cache = {"token": None, "expires_at": 0}
_AUTH_URL = "https://auth-api.robota.ua"
_TOKEN_TTL = 23 * 3600  # refresh every 23 hours


async def login_robotaua() -> str | None:
    """Get valid Bearer token. Auto-login if expired."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    email = os.getenv("ROBOTAUA_EMAIL")
    password = os.getenv("ROBOTAUA_PASSWORD")

    if not email or not password:
        jwt = os.getenv("ROBOTAUA_JWT")
        if jwt:
            logger.warning("ROBOTAUA_EMAIL/PASSWORD not set, using ROBOTAUA_JWT fallback")
            _token_cache["token"] = jwt
            _token_cache["expires_at"] = now + _TOKEN_TTL
            return jwt
        logger.error("No Robota.ua credentials available")
        return None

    try:
        async with cf_client(timeout=15) as client:
            resp = await client.post(f"{_AUTH_URL}/Login", json={
                "username": email,
                "password": password,
                "remember": True,
            }, _cf_no_retry=True)
            if resp.status_code == 200:
                token = resp.text.strip().strip('"')
                _token_cache["token"] = token
                _token_cache["expires_at"] = now + _TOKEN_TTL
                logger.info("Robota.ua login successful, token cached for 23h")
                return token
            else:
                logger.error(f"Robota.ua login failed: {resp.status_code} {resp.text[:200]}")
                jwt = os.getenv("ROBOTAUA_JWT")
                if jwt:
                    logger.warning("Falling back to ROBOTAUA_JWT env var")
                    _token_cache["token"] = jwt
                    _token_cache["expires_at"] = now + _TOKEN_TTL
                    return jwt
                return None
    except Exception as e:
        logger.error(f"Robota.ua login error: {e}")
        jwt = os.getenv("ROBOTAUA_JWT")
        if jwt:
            _token_cache["token"] = jwt
            _token_cache["expires_at"] = now + _TOKEN_TTL
        return jwt


def invalidate_token():
    """Call this on 401 response to force re-login on next call."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0


# Legacy sync shim used by robotaua_salary.py — wraps async login in a new event loop
def get_robotaua_token() -> str | None:
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't run nested — return cached token or env fallback
            if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
                return _token_cache["token"]
            return os.getenv("ROBOTAUA_JWT")
        return loop.run_until_complete(login_robotaua())
    except Exception:
        return os.getenv("ROBOTAUA_JWT")


def get_graphql_headers(token: str) -> dict:
    """Legacy — kept for any remaining callers."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def check_robotaua_auth() -> None:
    """
    Startup diagnostic: call login_robotaua() and log which auth path
    was actually used. Does NOT modify any auth logic.
    """
    email = os.getenv("ROBOTAUA_EMAIL")
    password = os.getenv("ROBOTAUA_PASSWORD")
    fallback_jwt = os.getenv("ROBOTAUA_JWT")

    token = await login_robotaua()

    if not token:
        logger.error(
            "Robota.ua auth failed completely — "
            "no token from credentials or ROBOTAUA_JWT fallback"
        )
        return

    # Detect which path was taken:
    # If email+password are set and the returned token differs from the
    # static JWT env var, live credential login succeeded.
    creds_configured = bool(email and password)
    token_matches_static_jwt = fallback_jwt and token == fallback_jwt

    if creds_configured and not token_matches_static_jwt:
        logger.info(
            "Robota.ua auth OK — "
            "using live credentials, JWT fallback not needed"
        )
    elif token_matches_static_jwt:
        logger.warning(
            "WARNING: Robota.ua falling back to JWT — "
            "check ROBOTAUA_EMAIL/PASSWORD (login endpoint may have rejected credentials)"
        )
    else:
        # No creds configured, JWT used as primary
        logger.warning(
            "WARNING: Robota.ua falling back to JWT — "
            "ROBOTAUA_EMAIL/PASSWORD not set, running on static token until April 12"
        )
