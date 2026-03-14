"""
Wine Enthusiast scraper - English source, NEEDS translation
Scrapes alcohol drink reviews from wineenthusiast.com
"""

import requests
import random
import time
import logging
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

LISTING_URLS = [
    "https://www.wineenthusiast.com/spirit-ratings/",
    "https://www.wineenthusiast.com/ratings/",
]


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "Referer": "https://www.google.com/",
    }


def _polite_delay():
    time.sleep(random.uniform(2.5, 5.0))


class WineEnthusiastScraper(ScraperBase):
    """Scraper for Wine Enthusiast drink reviews (English source)"""

    def get_source_name(self) -> str:
        return "Wine Enthusiast"

    def get_language(self) -> str:
        return "en"

    def get_needs_translation(self) -> bool:
        return True

    def get_article_links(self, limit: int = 5) -> List[str]:
        """Collect article URLs from both listing pages."""
        links = []
        seen = set()
        session = requests.Session()

        for listing_url in LISTING_URLS:
            if len(links) >= limit:
                break
            try:
                session.headers.update(_get_headers())
                resp = session.get(listing_url, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                cards = (
                    soup.select("article")
                    or soup.select(".review-card")
                    or soup.select(".rating-item")
                    or soup.select("[class*='review']")
                    or soup.select("[class*='rating']")
                )

                for card in cards:
                    if len(links) >= limit:
                        break
                    link = card.select_one("a[href]")
                    if not link:
                        continue
                    href = link.get("href", "")
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = "https://www.wineenthusiast.com" + href
                    if "wineenthusiast.com" not in href:
                        continue
                    if href in seen:
                        continue
                    seen.add(href)
                    links.append(href)

            except Exception as e:
                logger.error(f"Wine Enthusiast listing page failed ({listing_url}): {e}")
                continue

        return links

    def fetch_article(self, url: str) -> Optional[dict]:
        """Fetch and parse a single review page."""
        session = requests.Session()
        try:
            session.headers.update(_get_headers())
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            title_elem = (
                soup.select_one("h1")
                or soup.select_one(".review-title")
                or soup.select_one("[class*='title']")
            )
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                return None

            score_elem = (
                soup.select_one(".rating-score")
                or soup.select_one(".score")
                or soup.select_one("[class*='score']")
                or soup.select_one("[class*='points']")
                or soup.select_one(".review-score")
            )
            score = score_elem.get_text(strip=True) if score_elem else ""

            notes_elem = (
                soup.select_one(".tasting-notes")
                or soup.select_one(".review-description")
                or soup.select_one("[class*='tasting']")
                or soup.select_one("[class*='description']")
                or soup.select_one(".review-body")
                or soup.select_one("article p")
            )
            notes = notes_elem.get_text(strip=True) if notes_elem else ""

            if not notes and not score:
                try:
                    import trafilatura
                    downloaded = trafilatura.fetch_url(url)
                    if downloaded:
                        notes = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
                except Exception:
                    pass

            if score:
                content = f"Score: {score}/100\n\n{notes}".strip()
            else:
                content = notes.strip()

            if len(content) < 200:
                return None

            author_elem = (
                soup.select_one(".reviewer-name")
                or soup.select_one(".author")
                or soup.select_one("[class*='author']")
                or soup.select_one("[class*='reviewer']")
            )
            author = author_elem.get_text(strip=True) if author_elem else None

            date_elem = soup.select_one("time") or soup.select_one(".date") or soup.select_one("[class*='date']")
            published_date = None
            if date_elem:
                published_date = date_elem.get("datetime") or date_elem.get_text(strip=True)

            return {
                "title": title,
                "content": content,
                "url": url,
                "author": author,
                "published_date": published_date,
            }

        except Exception as e:
            logger.warning(f"Wine Enthusiast: failed to fetch article {url}: {e}")
            return None

    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape up to `limit` drink reviews from Wine Enthusiast."""
        articles = []
        logger.info("🔍 Scraping Wine Enthusiast (English)...")

        try:
            links = self.get_article_links(limit=limit)
            logger.info(f"  Found {len(links)} article links")

            seen_urls = set()
            for url in links:
                if len(articles) >= limit:
                    break
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                _polite_delay()

                try:
                    data = self.fetch_article(url)
                    if not data:
                        continue
                    if "Score" not in data["content"]:
                        logger.info(f"  Skipping (no score): {url}")
                        continue

                    article = ArticlePayload(
                        source_name=self.source_name,
                        language=self.language,
                        needs_translation=self.needs_translation,
                        url=data["url"],
                        title=data["title"],
                        content=data["content"],
                        published_at=data.get("published_date"),
                        author=data.get("author"),
                    )
                    articles.append(article)
                    logger.info(f"  ✅ {data['title'][:60]}...")

                except Exception as e:
                    logger.warning(f"  Skipping {url}: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Wine Enthusiast scraping failed: {e}")
            return []

        logger.info(f"✅ Scraped {len(articles)} articles from Wine Enthusiast")
        return articles

    def scrape(self, limit: int = 5) -> List[dict]:
        """Return plain dicts for standalone testing (no DB)."""
        articles = self.scrape_articles(limit=limit)
        return [
            {
                "title": a.title,
                "content": a.content,
                "url": a.url,
                "source": a.source_name,
                "author": a.author,
                "published_date": a.published_at,
                "status": "pending",
            }
            for a in articles
        ]
