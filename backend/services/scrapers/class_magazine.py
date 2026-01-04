"""
Class Magazine Scraper
Scrapes bar and cocktail industry news from classbarmag.com
UK-based bar industry publication covering cocktails, spirits, bartending, and hospitality
"""

import logging
import re
import time
from typing import List, Optional
from bs4 import BeautifulSoup
import requests
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

PHOTO_CREDIT_PATTERNS = [
    r'^Photo(?:s)?\s+by\s+[A-Za-z\s\.\-\']+$',
    r'^Image(?:s)?:\s+.*$',
    r'^Credit:\s+.*$',
    r'^Photo\s+courtesy\s+.*$',
    r'^\([Pp]hoto(?:s)?\s+by\s+[^)]+\)$',
    r'^©\s+.*$',
    r'^Photography:\s+.*$',
    r'^Image\s+credit:\s+.*$',
]

SKIP_PATTERNS = [
    r'^top\s+\d+',
    r'^\d+\s+best',
    r'^the\s+\d+\s+best',
    r'^ranking',
]

HEADER_GARBAGE_PATTERNS = [
    r'^PRINT\s*&?\s*DIGITAL$',
    r'^subscribe$',
    r'^SUBSCRIBE$',
    r'^Share\s*:?$',
    r'^Search$',
    r'^Menu$',
    r'^Home$',
    r'^News$',
    r'^here$',
    r'^here\.$',
]


class ClassMagazineScraper(ScraperBase):
    """Scraper for Class Magazine (UK bar industry)"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://classbarmag.com"
        self.news_url = f"{self.base_url}/news/categoryfront.php/id/11/News.html"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
    
    def get_source_name(self) -> str:
        return "Class Magazine"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def _is_list_article(self, title: str) -> bool:
        """Check if article is a ranking/list (which we want to skip)"""
        title_lower = title.lower()
        for pattern in SKIP_PATTERNS:
            if re.search(pattern, title_lower):
                return True
        return False
    
    def _clean_content(self, html_content: str) -> str:
        """Clean article content: remove photo credits, format properly"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for script in soup.find_all(['script', 'style', 'nav', 'footer', 'header']):
            script.decompose()
        
        for header_tag in soup.find_all(['h2', 'h3', 'h4']):
            header_text = header_tag.get_text(strip=True)
            if header_text:
                header_tag.replace_with(f"\n\n**{header_text}**\n\n")
        
        text = soup.get_text(separator='\n', strip=True)
        
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            skip_line = False
            for pattern in HEADER_GARBAGE_PATTERNS:
                if re.match(pattern, line, re.IGNORECASE):
                    skip_line = True
                    break
            if skip_line:
                continue
            
            is_photo_credit = False
            for pattern in PHOTO_CREDIT_PATTERNS:
                if re.match(pattern, line, re.IGNORECASE):
                    is_photo_credit = True
                    logger.debug(f"Removed photo credit: {line}")
                    break
            
            if not is_photo_credit:
                if re.search(r'[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30}$', line):
                    line = re.sub(r',?\s*[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,30}$', '', line)
            
            if not is_photo_credit and line:
                cleaned_lines.append(line)
        
        result = '\n'.join(cleaned_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result.strip()
    
    def _get_article_links(self, limit: int = 10) -> List[dict]:
        """Get article links from the news category page"""
        article_links = []
        seen_urls = set()
        
        try:
            logger.info(f"📡 Fetching news list: {self.news_url}")
            response = self.session.get(self.news_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            cards = soup.find_all('div', class_=re.compile(r'card'))
            
            for card in cards:
                link = card.find('a', href=True)
                if not link:
                    continue
                
                href = link.get('href', '')
                if 'fullstory.php' not in href:
                    continue
                
                if not href.startswith('http'):
                    href = f"{self.base_url}{href}" if href.startswith('/') else f"{self.base_url}/{href}"
                
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                title_elem = card.find('p', class_='card-text') or card.find('h4', class_='card-title')
                title = title_elem.get_text(strip=True) if title_elem else ''
                
                if not title or self._is_list_article(title):
                    continue
                
                category_elem = card.find('h4', class_='card-title')
                category = category_elem.get_text(strip=True) if category_elem else 'News'
                
                article_links.append({
                    'url': href,
                    'title': title,
                    'category': category
                })
                
                if len(article_links) >= limit:
                    break
            
            logger.info(f"📋 Found {len(article_links)} unique article links")
            
        except Exception as e:
            logger.error(f"Error fetching article links: {e}")
        
        return article_links
    
    def _scrape_article_content(self, url: str) -> Optional[tuple]:
        """Scrape full article content from article page. Returns (content, author, published_at)"""
        try:
            time.sleep(self.get_rate_limit_delay())
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            author = None
            published_at = None
            byline = soup.find('div', class_='social-byline-container')
            if byline:
                byline_text = byline.get_text()
                by_match = re.search(r'by\s+([A-Za-z\s]+)', byline_text)
                if by_match:
                    author = by_match.group(1).strip()
                date_match = re.search(r'/\s*(\d{1,2}\s+\w+,\s*\d{4})', byline_text)
                if date_match:
                    published_at = date_match.group(1).strip()
            
            article_text = soup.find('div', class_='article-text')
            if article_text:
                return self._clean_content(str(article_text)), author, published_at
            
            article_wrapper = soup.find('div', class_='article')
            if article_wrapper:
                for elem in article_wrapper.find_all(['div'], class_=['social-byline-container', 'article-social-bar']):
                    elem.decompose()
                return self._clean_content(str(article_wrapper)), author, published_at
            
            return None, None, None
            
        except Exception as e:
            logger.error(f"Error scraping article {url}: {e}")
            return None, None, None
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from Class Magazine"""
        articles = []
        
        try:
            article_links = self._get_article_links(limit=limit * 2)
            
            for link_data in article_links:
                if len(articles) >= limit:
                    break
                
                try:
                    url = link_data['url']
                    title = link_data['title']
                    category = link_data.get('category', 'News')
                    
                    logger.info(f"  📄 Scraping: {title[:50]}...")
                    
                    content, author, published_at = self._scrape_article_content(url)
                    
                    if not content:
                        logger.debug(f"No content extracted for: {title}")
                        continue
                    
                    if len(content) < 500:
                        logger.debug(f"Skipping short article ({len(content)} chars): {title}")
                        continue
                    
                    article = ArticlePayload(
                        title=title,
                        content=content,
                        url=url,
                        source_name=self.source_name,
                        language=self.language,
                        needs_translation=self.needs_translation,
                        published_at=published_at,
                        author=author,
                        tags=[category] if category else None
                    )
                    
                    articles.append(article)
                    logger.info(f"  ✅ {title[:60]}... ({len(content)} chars)")
                    
                except Exception as e:
                    logger.error(f"Error processing article: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} articles from {self.source_name}")
            
        except Exception as e:
            logger.error(f"❌ Scraping failed: {e}")
        
        return articles
    
    def get_rate_limit_delay(self) -> float:
        """Return delay between requests (respect the website)"""
        return 2.0
