import requests
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

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


def _is_logged_in(resp) -> bool:
    text = resp.text if hasattr(resp, 'text') else ''
    url = str(resp.url) if hasattr(resp, 'url') else ''
    return (
        "cabinet" in url
        or "Знайти кандидатів" in text
        or "Вийти" in text
        or "logout" in text
    )


def get_workua_session() -> Optional[requests.Session]:
    if not WORKUA_EMAIL or not WORKUA_PASSWORD:
        logger.warning("WORKUA_EMAIL/PASSWORD not configured")
        return None

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        url = "https://www.work.ua/employer/login/"
        logger.info(f"Work.ua login attempt: {url}")
        resp = session.get(url, timeout=15, allow_redirects=True)
        logger.info(f"Work.ua login page: {resp.status_code}, URL: {resp.url}")

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

        login_data = {
            "email": WORKUA_EMAIL,
            "password": WORKUA_PASSWORD,
        }
        if csrf_token:
            login_data["csrfmiddlewaretoken"] = csrf_token

        login_resp = session.post(
            url,
            data=login_data,
            timeout=15,
            allow_redirects=True,
        )
        logger.info(f"Work.ua login attempt: {url} → {login_resp.status_code}")
        logger.info(f"Response URL after redirect: {login_resp.url}")

        if _is_logged_in(login_resp):
            logger.info("Work.ua login successful (employer login)")
            return session
    except Exception as e:
        logger.warning(f"Work.ua employer login failed: {e}")

    try:
        url2 = "https://www.work.ua/api/v2/auth/login/"
        logger.info(f"Work.ua login attempt: {url2}")
        resp2 = session.post(
            url2,
            json={"email": WORKUA_EMAIL, "password": WORKUA_PASSWORD},
            timeout=15,
        )
        logger.info(f"Work.ua login attempt: {url2} → {resp2.status_code}")
        logger.info(f"Response URL after redirect: {resp2.url}")

        if resp2.status_code == 200:
            logger.info("Work.ua login successful (API v2)")
            return session
    except Exception as e:
        logger.warning(f"Work.ua API v2 login failed: {e}")

    try:
        url3 = "https://www.work.ua/uk/employer/"
        logger.info(f"Work.ua login attempt: {url3}")
        resp3 = session.get(url3, timeout=15, allow_redirects=True)
        logger.info(f"Work.ua login attempt: {url3} → {resp3.status_code}")
        logger.info(f"Response URL after redirect: {resp3.url}")

        if _is_logged_in(resp3):
            logger.info("Work.ua login successful (session cookies)")
            return session
    except Exception as e:
        logger.warning(f"Work.ua session check failed: {e}")

    logger.error("Work.ua login failed - all attempts exhausted")
    return None
