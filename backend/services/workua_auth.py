import requests
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

WORKUA_LOGIN_URL = "https://www.work.ua/login/"
WORKUA_EMAIL = os.getenv("WORKUA_EMAIL", "")
WORKUA_PASSWORD = os.getenv("WORKUA_PASSWORD", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def get_workua_session() -> Optional[requests.Session]:
    if not WORKUA_EMAIL or not WORKUA_PASSWORD:
        logger.warning("WORKUA_EMAIL/PASSWORD not configured")
        return None

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.get(WORKUA_LOGIN_URL, timeout=15)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        csrf_token = None

        meta = soup.find("meta", {"name": "csrftoken"})
        if meta:
            csrf_token = meta.get("content")

        if not csrf_token:
            inp = soup.find("input", {"name": "csrfmiddlewaretoken"})
            if inp:
                csrf_token = inp.get("value")

        if not csrf_token:
            csrf_token = session.cookies.get("csrftoken")

        if not csrf_token:
            logger.warning("Could not find CSRF token, attempting login anyway")

        login_data = {
            "email": WORKUA_EMAIL,
            "password": WORKUA_PASSWORD,
        }
        if csrf_token:
            login_data["csrfmiddlewaretoken"] = csrf_token

        login_resp = session.post(
            WORKUA_LOGIN_URL,
            data=login_data,
            timeout=15,
            allow_redirects=True,
        )

        if "logout" in login_resp.text or "cabinet" in login_resp.url:
            logger.info("Work.ua login successful")
            return session

        if "Знайти кандидатів" in login_resp.text:
            logger.info("Work.ua login successful (employer cabinet)")
            return session

        logger.error(f"Work.ua login failed - unexpected response URL: {login_resp.url}")
        return None

    except Exception as e:
        logger.error(f"Work.ua auth error: {e}")
        return None
