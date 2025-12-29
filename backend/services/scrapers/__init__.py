"""
Multi-source scraping architecture
Supports both English and Ukrainian news sources
"""

from .base import ScraperBase, ArticlePayload
from .spirits_business import SpiritsBusinessScraper
from .delo_ua import DeloUaScraper
from .minfin_ua import MinFinUaScraper
from .just_drinks import JustDrinksScraper
from .restorator_ua import RestoratorUaScraper
from .drinks_report import DrinksReportScraper
from .modern_restaurant_management import ModernRestaurantManagementScraper
from .manager import ScraperManager

__all__ = [
    'ScraperBase',
    'ArticlePayload',
    'SpiritsBusinessScraper',
    'DeloUaScraper',
    'MinFinUaScraper',
    'JustDrinksScraper',
    'RestoratorUaScraper',
    'DrinksReportScraper',
    'ModernRestaurantManagementScraper',
    'ScraperManager'
]
