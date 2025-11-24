"""
The Spirits Business scraper - English source, needs translation to Ukrainian
"""

import requests
from bs4 import BeautifulSoup
import trafilatura
import logging
import re
from typing import List, Optional
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class SpiritsBusinessScraper(ScraperBase):
    """Scraper for The Spirits Business (English source)"""
    
    def get_source_name(self) -> str:
        return "The Spirits Business"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape latest articles from The Spirits Business"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name}...")
            url = "https://www.thespiritsbusiness.com"
            
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            article_links = soup.find_all('a', href=re.compile(r'/\d{4}/\d{2}/'))
            
            seen_urls = set()
            
            for link in article_links:
                if len(articles) >= limit:
                    break
                
                article_url = link.get('href')
                if not article_url or article_url in seen_urls:
                    continue
                
                if not article_url.startswith('http'):
                    article_url = url + article_url
                
                seen_urls.add(article_url)
                
                # Get title from link
                title_elem = link.find('strong') or link.find(['h1', 'h2', 'h3'])
                if not title_elem:
                    title = link.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue
                else:
                    title = title_elem.get_text(strip=True)
                
                # Clean title
                title = self._clean_title(title)
                
                logger.info(f"  📄 Found: {title[:50]}...")
                
                # Fetch article content
                content_data = self._fetch_article_content(article_url)
                
                if content_data and content_data['content']:
                    article = ArticlePayload(
                        source_name=self.source_name,
                        language=self.language,
                        needs_translation=self.needs_translation,
                        url=article_url,
                        title=title,
                        content=content_data['content'],
                        author=content_data.get('author'),
                        published_at=content_data.get('published_date')
                    )
                    articles.append(article)
            
            logger.info(f"✅ Scraped {len(articles)} articles from {self.source_name}")
            return articles
            
        except Exception as e:
            logger.error(f"❌ {self.source_name} scraping failed: {e}")
            return []
    
    def _fetch_article_content(self, url: str) -> Optional[dict]:
        """Fetch and extract article content"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Use trafilatura for content extraction
            content = trafilatura.extract(
                response.content,
                include_comments=False,
                include_tables=False
            )
            
            if not content:
                return None
            
            # Extract author from content
            author = self._extract_author(content)
            
            # Clean content
            content = self._clean_content(content, "")
            
            # Extract date from URL (format: /YYYY/MM/)
            date_match = re.search(r'/(\d{4})/(\d{2})/', url)
            published_date = None
            if date_match:
                year, month = date_match.groups()
                published_date = f"{year}-{month}-01"
            
            return {
                'content': content,
                'author': author,
                'published_date': published_date
            }
            
        except Exception as e:
            logger.error(f"Error fetching content from {url}: {e}")
            return None
    
    def _clean_title(self, title: str) -> str:
        """Remove source name from title"""
        if not title:
            return ""
        
        patterns = [
            f' - {self.source_name}',
            f' | {self.source_name}',
            f' – {self.source_name}',
            f' — {self.source_name}',
        ]
        
        for pattern in patterns:
            if title.endswith(pattern):
                title = title[:-len(pattern)].strip()
                break
        
        return title
    
    def _clean_content(self, content: str, title: str) -> str:
        """Clean article content"""
        if not content:
            return ""
        
        # Remove title from beginning
        if title:
            title_escaped = re.escape(title)
            content = re.sub(f'^{title_escaped}\\s*', '', content, flags=re.IGNORECASE)
        
        # Remove byline
        byline_pattern = r'(?:^|\n)By\s+[A-Z][a-zA-Z\'\-\.]*(?:\s+[A-Z][a-zA-Z\'\-\.]*)*(?=\n|$|[A-Z][a-z]|[A-Z]{2,})'
        content = re.sub(byline_pattern, '\n', content, flags=re.MULTILINE)
        
        # Remove related content section
        content = re.split(r'Related news|Related articles|Related content', content, flags=re.IGNORECASE)[0]
        
        # Clean whitespace
        content = re.sub(r'\n\s*\n+', '\n\n', content)
        content = content.strip()
        
        return content
    
    def _extract_author(self, content: str) -> str:
        """Extract author name from content"""
        byline_pattern = r'(?:^|\n)By\s+([A-Z][a-zA-Z\'\-\.]*(?:\s+[A-Z][a-zA-Z\'\-\.]*)*?)(?=\n|$|[A-Z][a-z]|[A-Z]{2,})'
        match = re.search(byline_pattern, content, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
        return ""
