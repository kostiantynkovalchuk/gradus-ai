"""
Modern Restaurant Management Scraper
Scrapes HoReCa industry news and trends from modernrestaurantmanagement.com
"""

import logging
import re
from typing import List
from bs4 import BeautifulSoup
import feedparser
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

# Photo credit patterns to remove
PHOTO_CREDIT_PATTERNS = [
    r'^Photo(?:s)?\s+by\s+[A-Za-z\s\.\-\']+$',  # "Photo by Name" or "Photos by Name"
    r'^Top\s+photo:\s+.*$',  # "Top photo: ..."
    r'^Photo:\s+.*$',  # "Photo: ..."
    r'^Image(?:s)?:\s+.*$',  # "Image: ..." or "Images: ..."
    r'^Credit:\s+.*$',  # "Credit: ..."
    r'^Photo\s+courtesy\s+.*$',  # "Photo courtesy ..."
    r'^\([Pp]hoto(?:s)?\s+by\s+[^)]+\)$',  # "(Photo by Name)"
    r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s+[Pp]hoto(?:s)?$',  # "Name Name Photo(s)"
]


class ModernRestaurantManagementScraper(ScraperBase):
    """Scraper for Modern Restaurant Management"""
    
    def get_source_name(self) -> str:
        return "Modern Restaurant Management"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def _clean_content(self, html_content: str) -> str:
        """
        Clean content by removing photo credits and formatting subtitles.
        Returns clean text with markdown-style headers for subtitles.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Process headers (h2, h3, h4) to mark them as subtitles with markdown
        for header_tag in soup.find_all(['h2', 'h3', 'h4']):
            header_text = header_tag.get_text(strip=True)
            if header_text:
                # Replace header with markdown-style bold header
                header_tag.replace_with(f"\n\n**{header_text}**\n\n")
        
        # Get text content
        text = soup.get_text(separator='\n', strip=True)
        
        # Split into lines and clean
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if line matches any photo credit pattern
            is_photo_credit = False
            for pattern in PHOTO_CREDIT_PATTERNS:
                if re.match(pattern, line, re.IGNORECASE):
                    is_photo_credit = True
                    logger.debug(f"Removed photo credit: {line}")
                    break
            
            # Also remove inline photo credits like "Photos by Joseph D. Tran"
            if not is_photo_credit:
                # Check for inline photo credits at start or end of line
                if re.search(r'[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30}$', line):
                    # Remove trailing photo credit from line
                    line = re.sub(r',?\s*[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30}$', '', line)
                if re.match(r'^[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30},?\s*', line):
                    # Remove leading photo credit from line
                    line = re.sub(r'^[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30},?\s*', '', line)
            
            if not is_photo_credit and line:
                cleaned_lines.append(line)
        
        # Join lines with proper spacing
        result = '\n'.join(cleaned_lines)
        
        # Clean up excessive newlines
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result.strip()
    
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
                    
                    html_content = ""
                    if hasattr(entry, 'content') and entry.content:
                        html_content = entry.content[0].value
                    elif hasattr(entry, 'summary'):
                        html_content = entry.summary
                    
                    # Use custom content cleaner to remove photo credits and format subtitles
                    content = self._clean_content(html_content) if html_content else ""
                    
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
