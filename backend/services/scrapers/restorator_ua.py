"""
Restorator.ua scraper - Ukrainian source, NO translation needed
Scrapes HoReCa (Hotel/Restaurant/Catering) industry news from restorator.ua
"""

import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Optional
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class RestoratorUaScraper(ScraperBase):
    """Scraper for HoReCa-Україна (horeca-ukraine.com) - Ukrainian HoReCa news"""
    
    def get_source_name(self) -> str:
        return "HoReCa-Україна"
    
    def get_language(self) -> str:
        return "uk"
    
    def get_needs_translation(self) -> bool:
        return False
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from HoReCa-Україна HoReCa news section"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name} (Ukrainian)...")
            posts_url = "https://horeca-ukraine.com/category/horeca-news/"
            
            headers = {'User-Agent': self.user_agent}
            response = requests.get(posts_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article cards
            article_elements = (
                soup.select('.post-item') or
                soup.select('article') or
                soup.select('.news-item') or
                soup.select('.card') or
                soup.select('.item') or
                soup.select('div[class*="post"]')
            )
            
            logger.info(f"  Found {len(article_elements)} potential articles")
            
            for element in article_elements[:limit * 2]:
                if len(articles) >= limit:
                    break
                
                try:
                    article_data = self._parse_article_card(element)
                    
                    if not article_data:
                        continue
                    
                    # Fetch full article content (pass title for duplicate removal)
                    content = self._fetch_article_content(article_data['url'], article_data['title'])
                    
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
            # Find title
            title_elem = (
                element.select_one('h2') or
                element.select_one('h3') or
                element.select_one('.title') or
                element.select_one('.post-title') or
                element.select_one('.card-title') or
                element.select_one('[class*="title"]')
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
                base_url = "https://restorator.ua"
                url = base_url + url if url.startswith('/') else f"{base_url}/{url}"
            
            # Find image (optional)
            img_elem = element.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    image_url = f"https:{image_url}" if image_url.startswith('//') else f"https://restorator.ua{image_url}"
            
            # Find date (optional)
            date_elem = element.select_one('.date') or element.select_one('time') or element.select_one('.published')
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
    
    def _fetch_article_content(self, url: str, title: str = "") -> Optional[str]:
        """Fetch full article content from article page"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article content
            content_elem = (
                soup.select_one('.post-content') or
                soup.select_one('article') or
                soup.select_one('.content') or
                soup.select_one('.entry-content') or
                soup.select_one('.article-body') or
                soup.select_one('[class*="content"]')
            )
            
            if not content_elem:
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements (ads, scripts, social, etc.)
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, nav, footer, .related, .comments, .share'):
                unwanted.decompose()
            
            # Remove metadata elements BEFORE extracting text
            metadata_selectors = [
                '.article-meta', '.meta', '.metadata', '.post-meta', '.entry-meta',
                '.category', '.post-category', '.article-category',
                '.breadcrumb', '.breadcrumbs',
                '.tags', '.post-tags', '.article-tags',
                '.related', '.related-posts', '.related-articles',
                '.footer-text', '.disclaimer', '.copyright',
                '.author', '.post-author', '.date', '.post-date'
            ]
            for selector in metadata_selectors:
                for element in content_elem.select(selector):
                    element.decompose()
            
            # Extract text
            content = content_elem.get_text(separator='\n', strip=True)
            
            # Clean content (remove metadata patterns, duplicate title, fix formatting)
            content = self._clean_content(content, title)
            
            return content
            
        except Exception as e:
            logger.error(f"Error fetching content from {url}: {e}")
            return None
    
    def _clean_content(self, content: str, title: str) -> str:
        """Clean HoReCa article content - remove metadata, duplicates, fix formatting"""
        import re
        
        if not content:
            return ""
        
        # Remove duplicate title if present anywhere near the start (within first 500 chars)
        if title and len(title) > 15:
            # Check for exact match at start
            if content.startswith(title):
                content = content[len(title):].strip()
            else:
                # Check if title appears in the first 500 chars
                title_pos = content[:500].find(title)
                if title_pos >= 0:
                    content = content[:title_pos] + content[title_pos + len(title):]
                    content = content.strip()
        
        # Remove HoReCa-specific metadata and footer patterns
        patterns_to_remove = [
            r'Pro-HoReCa\s*/?\s*Статті.*?\n',
            r'Pro-HoReCa.*?\n',
            r'^Статті\s*\n',
            r'Цікаве за цей тиждень:.*',
            r'Усі представлені фото.*',
            r'Усі права захищені.*',
            r'Новини Ресторанів.*?\n',
            r'Аналітичні огляди.*?\n',
            r'Тенденції ринку.*?\n',
            r'Постачальники HoReCa.*?\n',
            r'Подивитися всі.*?\n',
            r'Поділитися.*?\n',
            r'Share.*?\n',
        ]
        
        for pattern in patterns_to_remove:
            content = re.sub(pattern, '', content, flags=re.MULTILINE | re.IGNORECASE)
        
        # Split into lines and clean
        lines = content.split('\n')
        cleaned_lines = []
        
        # Words/phrases to skip as standalone lines (metadata/UI)
        skip_words = {
            'Pro-HoReCa', 'Статті', 'Новини', 'Категорія',
            'Цікаве за цей тиждень', 'Усі представлені фото',
            'Аналітичні огляди', 'Тенденції ринку', 'Постачальники HoReCa',
            'Подивитися всі', 'Поділитися', 'Share', 'Facebook', 'Twitter',
            'Telegram', 'Viber', 'Коментарі', 'Реклама', 'Новини Ресторанів'
        }
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip metadata/UI words
            if line in skip_words:
                continue
            
            # Skip lines containing metadata phrases
            skip_line = False
            for skip_word in skip_words:
                if skip_word in line and len(line) < 50:
                    skip_line = True
                    break
            if skip_line:
                continue
            
            # Skip very short lines that are likely navigation/UI
            if len(line) < 10 and not line.endswith('.'):
                continue
            
            cleaned_lines.append(line)
        
        # Join with double newline for paragraph separation
        content = '\n\n'.join(cleaned_lines)
        
        # Remove multiple consecutive newlines (more than 2)
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Remove non-breaking spaces and zero-width spaces
        content = content.replace('\xa0', ' ')
        content = content.replace('\u200b', '')
        
        # Remove multiple spaces
        content = re.sub(r' +', ' ', content)
        
        return content.strip()
    
    def _clean_text(self, text: str) -> str:
        """Legacy method - redirects to _clean_content"""
        return self._clean_content(text, "")
