"""
The Spirits Business Reviews scraper - English source, needs translation
Targets the spirits-reviews section of thespiritsbusiness.com
"""

import requests
import re
import time
import random
import logging
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

LISTING_URL = "https://www.thespiritsbusiness.com/category/news/"
BASE_URL = "https://www.thespiritsbusiness.com"

LISTICLE_SKIP = ("Top 10", "Best ", "Ranking", "List of")


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.thespiritsbusiness.com/",
    }


def _polite_delay():
    time.sleep(random.uniform(2.0, 4.0))


class TheSpiritsBusinessReviewsScraper(ScraperBase):
    """Scraper for The Spirits Business — spirits-reviews section (English source)"""

    def get_source_name(self) -> str:
        return "The Spirits Business Reviews"

    def get_language(self) -> str:
        return "en"

    def get_needs_translation(self) -> bool:
        return True

    def get_article_links(self, limit: int = 5) -> List[str]:
        """Extract article URLs from the spirits-reviews listing page."""
        links = []
        seen = set()
        try:
            resp = requests.get(LISTING_URL, headers=_get_headers(), timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")

            for a in soup.find_all("a", href=re.compile(r"/\d{4}/\d{2}/")):
                if len(links) >= limit:
                    break
                href = a.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = BASE_URL + href
                if "thespiritsbusiness.com" not in href:
                    continue
                if href in seen:
                    continue
                seen.add(href)

                title_text = a.get_text(strip=True).lower()
                if any(skip.lower() in title_text for skip in LISTICLE_SKIP):
                    logger.info(f"  Skipping listicle: {title_text[:50]}")
                    continue

                links.append(href)

        except Exception as e:
            logger.error(f"TheSpiritsBusinessReviews listing page failed: {e}")

        return links

    def fetch_article(self, url: str) -> Optional[dict]:
        """Fetch and parse a single review article."""
        try:
            resp = requests.get(url, headers=_get_headers(), timeout=15)
            resp.raise_for_status()

            try:
                import trafilatura
                content = trafilatura.extract(
                    resp.content,
                    include_comments=False,
                    include_tables=False,
                ) or ""
            except Exception:
                soup = BeautifulSoup(resp.content, "html.parser")
                body = (
                    soup.select_one(".entry-content")
                    or soup.select_one("article")
                    or soup.select_one(".post-content")
                )
                content = body.get_text(separator="\n", strip=True) if body else ""

            if len(content) < 300:
                return None

            soup = BeautifulSoup(resp.content, "html.parser")

            title_elem = soup.find("h1") or soup.find("title")
            title = title_elem.get_text(strip=True) if title_elem else ""
            for suffix in (
                " - The Spirits Business",
                " | The Spirits Business",
                " – The Spirits Business",
                " — The Spirits Business",
            ):
                if title.endswith(suffix):
                    title = title[: -len(suffix)].strip()
                    break

            if not title:
                return None

            if any(skip in title for skip in LISTICLE_SKIP):
                return None

            author_elem = (
                soup.select_one(".author")
                or soup.select_one(".byline")
                or soup.select_one("[class*='author']")
            )
            author = author_elem.get_text(strip=True) if author_elem else None

            date_match = re.search(r"/(\d{4})/(\d{2})/", url)
            published_date = None
            if date_match:
                year, month = date_match.groups()
                published_date = f"{year}-{month}-01"

            content = self._clean_content(content, title)

            return {
                "title": title,
                "content": content,
                "url": url,
                "source": self.source_name,
                "author": author,
                "published_date": published_date,
            }

        except Exception as e:
            logger.warning(f"TheSpiritsBusinessReviews: failed to fetch {url}: {e}")
            return None

    def _clean_content(self, content: str, title: str) -> str:
        """Remove duplicate titles, bylines and related-content noise."""
        if not content:
            return ""
        if title:
            title_esc = re.escape(title)
            content = re.sub(f"^{title_esc}\\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(
            r"(?:^|\n)By\s+[A-Z][a-zA-Z'\-\.]*(?:\s+[A-Z][a-zA-Z'\-\.]*)*(?=\n|$)",
            "\n",
            content,
            flags=re.MULTILINE,
        )
        content = re.split(r"Related news|Related articles|Related content", content, flags=re.IGNORECASE)[0]
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        filtered = [
            l for l in lines
            if not (title and l.lower() == title.lower())
            and not re.match(r"^\d{1,2}\s+\w+,?\s+\d{4}$", l)
            and not (len(l) < 15 and not l.endswith("."))
        ]
        text = " ".join(filtered)
        text = re.sub(r"  +", " ", text)
        text = re.sub(r"([.!?»\"]\s+)([A-ZА-ЯІЇЄ])", r"\1\n\n\2", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape up to `limit` review articles."""
        articles = []
        logger.info("🔍 Scraping The Spirits Business Reviews (English)...")

        try:
            links = self.get_article_links(limit=limit)
            logger.info(f"  Found {len(links)} review links")

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
            logger.error(f"❌ The Spirits Business Reviews scraping failed: {e}")
            return []

        logger.info(f"✅ Scraped {len(articles)} articles from The Spirits Business Reviews")
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
