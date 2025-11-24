"""
Base scraper interface for multi-source content ingestion
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import hashlib

@dataclass
class ArticlePayload:
    """Standardized article data structure"""
    source_name: str
    language: str
    needs_translation: bool
    url: str
    title: str
    content: str
    published_at: Optional[str] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    tags: Optional[List[str]] = None
    
    def get_content_hash(self) -> str:
        """Generate hash for duplicate detection"""
        slug = f"{self.title}_{self.published_at or ''}"
        return hashlib.md5(slug.encode()).hexdigest()

class ScraperBase(ABC):
    """Base class for all news scrapers"""
    
    def __init__(self):
        self.source_name = self.get_source_name()
        self.language = self.get_language()
        self.needs_translation = self.get_needs_translation()
        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    
    @abstractmethod
    def get_source_name(self) -> str:
        """Return the human-readable source name"""
        pass
    
    @abstractmethod
    def get_language(self) -> str:
        """Return source language code (en, uk, ru, etc.)"""
        pass
    
    @abstractmethod
    def get_needs_translation(self) -> bool:
        """Return whether articles need translation"""
        pass
    
    @abstractmethod
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """
        Scrape articles from the source
        
        Args:
            limit: Maximum number of articles to scrape
            
        Returns:
            List of ArticlePayload objects
        """
        pass
    
    def is_enabled(self) -> bool:
        """Check if scraper is enabled (override for configuration)"""
        return True
    
    def get_rate_limit_delay(self) -> float:
        """Return delay between requests in seconds"""
        return 1.0
