import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class NewsScraper:
    def __init__(self):
        self.sources = [
            {
                "name": "The Drinks Business",
                "url": "https://www.thedrinksbusiness.com",
                "category": "drinks"
            },
            {
                "name": "The Spirits Business",
                "url": "https://www.thespiritsbusiness.com",
                "category": "spirits"
            }
        ]
    
    async def scrape_latest_articles(self, limit: int = 5) -> List[Dict]:
        """
        Scrape latest articles from configured news sources.
        Returns a list of articles with title, content, and source URL.
        """
        articles = []
        
        for source in self.sources:
            try:
                logger.info(f"Scraping {source['name']}...")
                source_articles = await self._scrape_source(source, limit)
                articles.extend(source_articles)
            except Exception as e:
                logger.error(f"Error scraping {source['name']}: {str(e)}")
                continue
        
        return articles
    
    async def _scrape_source(self, source: Dict, limit: int) -> List[Dict]:
        """
        Scrape articles from a specific source.
        This is a placeholder implementation - will need to be customized per source.
        """
        articles = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(source['url'], headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            article_data = {
                'source': source['name'],
                'source_url': source['url'],
                'title': 'Placeholder Title',
                'content': 'Placeholder content - scraper needs site-specific implementation',
                'excerpt': 'This is a placeholder. Implement site-specific scraping logic.',
                'category': source['category']
            }
            articles.append(article_data)
            
            logger.info(f"Found {len(articles)} articles from {source['name']}")
            
        except Exception as e:
            logger.error(f"Error scraping {source['url']}: {str(e)}")
            raise
        
        return articles[:limit]

news_scraper = NewsScraper()
