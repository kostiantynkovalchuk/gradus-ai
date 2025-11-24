"""
Scraper Manager - coordinates multiple news sources
Handles deduplication and content ingestion
"""

import logging
from typing import List, Dict, Set
from .base import ArticlePayload
from .spirits_business import SpiritsBusinessScraper
from .delo_ua import DeloUaScraper
from .minfin_ua import MinFinUaScraper
from .just_drinks import JustDrinksScraper

logger = logging.getLogger(__name__)

class ScraperManager:
    """Manages multiple news scrapers and coordinates content ingestion"""
    
    def __init__(self):
        self.scrapers = {
            'spirits_business': SpiritsBusinessScraper(),
            'delo_ua': DeloUaScraper(),
            'minfin_ua': MinFinUaScraper(),
            'just_drinks': JustDrinksScraper()
        }
    
    def scrape_all_sources(self, limit_per_source: int = 5) -> Dict[str, List[ArticlePayload]]:
        """
        Scrape all enabled sources
        
        Args:
            limit_per_source: Maximum articles per source
            
        Returns:
            Dict mapping source name to list of articles
        """
        results = {}
        total_articles = 0
        
        logger.info(f"🔄 Starting multi-source scraping...")
        
        for source_name, scraper in self.scrapers.items():
            if not scraper.is_enabled():
                logger.info(f"⏭️  Skipping disabled source: {source_name}")
                continue
            
            try:
                articles = scraper.scrape_articles(limit=limit_per_source)
                results[source_name] = articles
                total_articles += len(articles)
                
                logger.info(f"  ✅ {source_name}: {len(articles)} articles")
                
            except Exception as e:
                logger.error(f"  ❌ {source_name} failed: {e}")
                results[source_name] = []
        
        logger.info(f"✅ Multi-source scraping complete: {total_articles} total articles from {len(results)} sources")
        
        return results
    
    def scrape_source(self, source_name: str, limit: int = 5) -> List[ArticlePayload]:
        """
        Scrape a specific source
        
        Args:
            source_name: Name of the source to scrape
            limit: Maximum articles to scrape
            
        Returns:
            List of articles
        """
        scraper = self.scrapers.get(source_name)
        
        if not scraper:
            logger.error(f"Unknown source: {source_name}")
            return []
        
        if not scraper.is_enabled():
            logger.warning(f"Source disabled: {source_name}")
            return []
        
        try:
            articles = scraper.scrape_articles(limit=limit)
            logger.info(f"✅ {source_name}: scraped {len(articles)} articles")
            return articles
        except Exception as e:
            logger.error(f"❌ {source_name} scraping failed: {e}")
            return []
    
    def check_duplicate(self, article: ArticlePayload, existing_urls: Set[str], existing_hashes: Set[str]) -> bool:
        """
        Check if article is a duplicate
        
        Args:
            article: Article to check
            existing_urls: Set of existing source URLs
            existing_hashes: Set of existing content hashes
            
        Returns:
            True if duplicate, False if new
        """
        # Check URL
        if article.url in existing_urls:
            return True
        
        # Check content hash
        content_hash = article.get_content_hash()
        if content_hash in existing_hashes:
            return True
        
        return False
    
    def get_enabled_sources(self) -> List[str]:
        """Get list of enabled source names"""
        return [name for name, scraper in self.scrapers.items() if scraper.is_enabled()]
    
    def get_all_sources(self) -> List[str]:
        """Get list of all source names"""
        return list(self.scrapers.keys())

# Singleton instance
scraper_manager = ScraperManager()
