"""
Multi-source scraping architecture
Supports both English and Ukrainian news sources
"""

from .base import ScraperBase, ArticlePayload
from .spirits_business import SpiritsBusinessScraper
from .delo_ua import DeloUaScraper
from .minfin_ua import MinFinUaScraper
from .just_drinks import JustDrinksScraper
from .manager import ScraperManager

__all__ = [
    'ScraperBase',
    'ArticlePayload',
    'SpiritsBusinessScraper',
    'DeloUaScraper',
    'MinFinUaScraper',
    'JustDrinksScraper',
    'ScraperManager'
]
