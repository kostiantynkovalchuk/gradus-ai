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


def get_workua_session() -> Optional[requests.Session]:
    if not WORKUA_EMAIL or not WORKUA_PASSWORD:
        logger.warning("WORKUA_EMAIL/PASSWORD not configured")
        return None

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        resp = session.get(
            "https://www.work.ua/employer/login/",
            timeout=15,
            allow_redirects=True,
        )

        if "check_cookie" in resp.url:
            logger.info("Work.ua check_cookie redirect detected")
            session.cookies.set("check_cookie", "1", domain=".work.ua")
            resp = session.get(
                "https://www.work.ua/employer/login/",
                timeout=15,
                allow_redirects=True,
            )

        logger.info(f"Login page loaded: {resp.status_code}, {resp.url}")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        csrf_token = None
        inp = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if inp:
            csrf_token = inp.get("value")
        if not csrf_token:
            csrf_token = session.cookies.get("csrftoken")

        logger.info(f"CSRF token found: {bool(csrf_token)}")

        login_data = {
            "email": WORKUA_EMAIL,
            "password": WORKUA_PASSWORD,
            "next": "/employer/candidates/",
        }
        if csrf_token:
            login_data["csrfmiddlewaretoken"] = csrf_token

        login_resp = session.post(
            "https://www.work.ua/employer/login/",
            data=login_data,
            timeout=15,
            allow_redirects=True,
            headers={
                **session.headers,
                "Referer": "https://www.work.ua/employer/login/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        logger.info(f"Login POST: {login_resp.status_code}, URL: {login_resp.url}")
        logger.info(f"Response preview: {login_resp.text[:300]}")

        success_indicators = [
            "logout", "cabinet", "Знайти кандидатів",
            "Вийти", "employer/candidates",
        ]
        if any(s in login_resp.text or s in login_resp.url for s in success_indicators):
            logger.info("Work.ua login successful")
            return session

        logger.error(f"Work.ua login failed. Final URL: {login_resp.url}")
        logger.error(f"Response: {login_resp.text[:500]}")
        return None

    except Exception as e:
        logger.error(f"Work.ua auth error: {e}")
        return None
