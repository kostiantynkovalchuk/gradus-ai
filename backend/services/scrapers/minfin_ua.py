"""
MinFin.ua scraper - Ukrainian source, NO translation needed
Scrapes alcohol market news from minfin.com.ua
"""

import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Optional
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class MinFinUaScraper(ScraperBase):
    """Scraper for MinFin.ua alcohol market section (Ukrainian source)"""
    
    def get_source_name(self) -> str:
        return "MinFin.ua"
    
    def get_language(self) -> str:
        return "uk"
    
    def get_needs_translation(self) -> bool:
        return False
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from MinFin.ua alcohol market section"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name} (Ukrainian)...")
            section_url = "https://minfin.com.ua/ua/company/alkogol/"
            
            headers = {'User-Agent': self.user_agent}
            response = requests.get(section_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article cards
            article_elements = (
                soup.select('.mfn-table-item') or
                soup.select('.news-item') or
                soup.select('.article-item') or
                soup.select('.list-item') or
                soup.select('tr[class*="item"]') or
                soup.find_all('div', class_='item')
            )
            
            logger.info(f"  Found {len(article_elements)} potential articles")
            
            for element in article_elements[:limit * 2]:
                if len(articles) >= limit:
                    break
                
                try:
                    article_data = self._parse_article_card(element)
                    
                    if not article_data:
                        continue
                    
                    # Fetch full article content
                    content = self._fetch_article_content(article_data['url'])
                    
                    if content and len(content) > 100:
                        article = ArticlePayload(
                            source_name=self.source_name,
                            language=self.language,
                            needs_translation=self.needs_translation,
                            url=article_data['url'],
                            title=article_data['title'],
                            content=content,
                            published_at=article_data.get('published_date'),
                            image_url=article_data.get('image_url')
                        )
                        articles.append(article)
                        logger.info(f"  ✅ {article_data['title'][:50]}...")
                        
                except Exception as e:
                    logger.error(f"  Error parsing article element: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} Ukrainian articles from {self.source_name}")
            return articles
            
        except Exception as e:
            logger.error(f"❌ {self.source_name} scraping failed: {e}")
            return []
    
    def _parse_article_card(self, element) -> Optional[dict]:
        """Parse article card from listing page"""
        try:
            # Find title - MinFin uses various structures
            title_elem = (
                element.select_one('h2') or
                element.select_one('h3') or
                element.select_one('.title') or
                element.select_one('.mfn-table-header') or
                element.select_one('[class*="title"]') or
                element.select_one('a')
            )
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            
            if len(title) < 10:
                return None
            
            # Find link
            link_elem = title_elem.find_parent('a') or element.select_one('a')
            
            if not link_elem:
                return None
            
            url = link_elem.get('href')
            if not url:
                return None
            
            # Make URL absolute
            if not url.startswith('http'):
                base_url = "https://minfin.com.ua"
                url = base_url + url if url.startswith('/') else f"{base_url}/{url}"
            
            # Find image (optional)
            img_elem = element.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    image_url = f"https:{image_url}" if image_url.startswith('//') else f"https://minfin.com.ua{image_url}"
            
            # Find date (optional)
            date_elem = element.select_one('.date') or element.select_one('time') or element.select_one('.mfn-table-date')
            published_date = None
            if date_elem:
                published_date = date_elem.get_text(strip=True)
            
            return {
                'title': title,
                'url': url,
                'image_url': image_url,
                'published_date': published_date
            }
            
        except Exception as e:
            logger.error(f"Error parsing article card: {e}")
            return None
    
    def _fetch_article_content(self, url: str) -> Optional[str]:
        """Fetch full article content from article page"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article content
            content_elem = (
                soup.select_one('.article-content') or
                soup.select_one('.mfn-article-content') or
                soup.select_one('.content') or
                soup.select_one('article') or
                soup.select_one('main') or
                soup.select_one('.main-content') or
                soup.select_one('[class*="content"]')
            )
            
            if not content_elem:
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, nav, footer, .related, .comments, .share, .social'):
                unwanted.decompose()
            
            # Extract text
            content = content_elem.get_text(separator='\n', strip=True)
            
            # Clean text
            content = self._clean_text(content)
            
            return content
            
        except Exception as e:
            logger.error(f"Error fetching content from {url}: {e}")
            return None
    
    def _clean_text(self, text: str) -> str:
        """Clean scraped Ukrainian text"""
        if not text:
            return ""
        
        # Remove extra whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n\n'.join(lines)
        
        # Remove non-breaking spaces
        text = text.replace('\xa0', ' ')
        text = text.replace('\u200b', '')
        
        # Remove very short lines (likely navigation/UI elements)
        lines = text.split('\n\n')
        lines = [line for line in lines if len(line) > 20]
        text = '\n\n'.join(lines)
        
        # Remove multiple spaces
        import re
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
