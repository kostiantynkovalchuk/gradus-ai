"""
Modern Restaurant Management Scraper
Scrapes HoReCa industry news and trends from modernrestaurantmanagement.com
"""

import logging
from typing import List
from bs4 import BeautifulSoup
import feedparser
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)


class ModernRestaurantManagementScraper(ScraperBase):
    """Scraper for Modern Restaurant Management"""
    
    def get_source_name(self) -> str:
        return "Modern Restaurant Management"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from RSS feed"""
        articles = []
        
        try:
            rss_url = "https://modernrestaurantmanagement.com/feed/"
            logger.info(f"📡 Fetching RSS: {rss_url}")
            
            feed = feedparser.parse(rss_url)
            
            if not feed.entries:
                logger.warning("No entries in RSS feed")
                return articles
            
            logger.info(f"📋 Found {len(feed.entries)} articles in RSS")
            
            for entry in feed.entries[:limit]:
                try:
                    title = entry.get('title', 'No title')
                    url = entry.get('link', '')
                    
                    content = ""
                    if hasattr(entry, 'content') and entry.content:
                        content = entry.content[0].value
                    elif hasattr(entry, 'summary'):
                        content = entry.summary
                    
                    if content:
                        soup = BeautifulSoup(content, 'html.parser')
                        content = soup.get_text(separator='\n', strip=True)
                    
                    if len(content) < 200:
                        logger.debug(f"Skipping short article: {title[:50]}")
                        continue
                    
                    published = None
                    if hasattr(entry, 'published'):
                        published = entry.published
                    
                    author = None
                    if hasattr(entry, 'author'):
                        author = entry.author
                    
                    article = ArticlePayload(
                        title=title,
                        content=content,
                        url=url,
                        source_name=self.source_name,
                        language=self.language,
                        needs_translation=self.needs_translation,
                        published_at=published,
                        author=author
                    )
                    
                    articles.append(article)
                    logger.info(f"  ✅ {title[:60]}...")
                    
                except Exception as e:
                    logger.error(f"Error parsing entry: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} articles from {self.source_name}")
            
        except Exception as e:
            logger.error(f"❌ RSS scraping failed: {e}")
        
        return articles
