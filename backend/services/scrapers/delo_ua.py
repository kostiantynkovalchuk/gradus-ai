"""
Delo.ua scraper - Ukrainian source, NO translation needed
Scrapes alcohol/business news from delo.ua using Playwright for JavaScript rendering
"""

import logging
from typing import List, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import requests
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class DeloUaScraper(ScraperBase):
    """Scraper for Delo.ua alcohol/business section (Ukrainian source)"""
    
    def get_source_name(self) -> str:
        return "Delo.ua"
    
    def get_language(self) -> str:
        return "uk"
    
    def get_needs_translation(self) -> bool:
        return False
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from Delo.ua retail section using Playwright"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name} (Ukrainian) with Playwright...")
            section_url = "https://delo.ua/business/retail/"
            
            with sync_playwright() as p:
                # Launch browser in headless mode
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.user_agent)
                
                try:
                    # Navigate to the page and wait for content to load
                    page.goto(section_url, wait_until='networkidle', timeout=30000)
                    
                    # Wait for article elements to appear (try multiple selectors)
                    try:
                        page.wait_for_selector('article, .article-item, .news-item, a[href*="/business/"]', timeout=10000)
                    except PlaywrightTimeoutError:
                        logger.warning(f"  Timeout waiting for articles to load")
                    
                    # Get the fully rendered HTML
                    html_content = page.content()
                    
                finally:
                    browser.close()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find article headings (h2, h3)
            headings = soup.select('h2, h3')
            
            logger.info(f"  Found {len(headings)} potential articles")
            
            for heading in headings[:limit * 2]:  # Get more than needed to account for filtering
                if len(articles) >= limit:
                    break
                
                try:
                    article_data = self._parse_article_heading(heading)
                    
                    if not article_data:
                        continue
                    
                    # Skip navigation links (too short URLs or category pages)
                    if article_data['url'].endswith(('/business/', '/retail/', '/news-feed/', '/articles/')):
                        continue
                    
                    # Fetch full article content
                    content = self._fetch_article_content(article_data['url'])
                    
                    if content and len(content) > 100:  # Minimum content length
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
                    logger.error(f"  Error parsing article heading: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} Ukrainian articles from {self.source_name}")
            return articles
            
        except Exception as e:
            logger.error(f"❌ {self.source_name} scraping failed: {e}")
            return []
    
    def _parse_article_heading(self, heading) -> Optional[dict]:
        """Parse article data from heading element"""
        try:
            # Get title from heading
            title = heading.get_text(strip=True)
            
            # Remove "АктуальноАктуально" prefix if present
            title = title.replace('АктуальноАктуально', '').strip()
            
            if len(title) < 15:  # Too short to be a real article title
                return None
            
            # Find link - check if heading is inside a link or has a link child
            link_elem = heading.find_parent('a') or heading.find('a')
            
            if not link_elem:
                return None
            
            url = link_elem.get('href')
            if not url:
                return None
            
            # Make URL absolute
            if not url.startswith('http'):
                base_url = "https://delo.ua"
                url = base_url + url if url.startswith('/') else f"{base_url}/{url}"
            
            # Find image (optional) - look in parent container
            parent_container = heading.find_parent('div') or heading.find_parent('article')
            img_elem = None
            if parent_container:
                img_elem = parent_container.select_one('img')
            
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    image_url = f"https:{image_url}" if image_url.startswith('//') else f"https://delo.ua{image_url}"
            
            # Find date (optional)
            date_elem = None
            if parent_container:
                date_elem = parent_container.select_one('.date') or parent_container.select_one('.time') or parent_container.select_one('time')
            
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
            logger.error(f"Error parsing article heading: {e}")
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
                soup.select_one('.post-content') or
                soup.select_one('.entry-content') or
                soup.select_one('article') or
                soup.select_one('.article-body') or
                soup.select_one('[class*="content"]')
            )
            
            if not content_elem:
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, .related, .comments, .share, .social'):
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
        text = text.replace('\u200b', '')  # Zero-width space
        
        # Remove multiple spaces
        import re
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
