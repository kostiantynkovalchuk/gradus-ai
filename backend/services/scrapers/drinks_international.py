"""
Drinks International scraper - English source, NEEDS translation
Scrapes vodka and spirits news from drinksint.com
"""

import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Optional
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class DrinksInternationalScraper(ScraperBase):
    """Scraper for Drinks International vodka news (English source)"""
    
    def get_source_name(self) -> str:
        return "Drinks International"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from Drinks International vodka news section"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name} (English)...")
            vodka_news_url = "https://drinksint.com/news/categoryfront.php/id/209/Vodka_news.html"
            
            headers = {'User-Agent': self.user_agent}
            response = requests.get(vodka_news_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links to articles (fullstory.php pattern)
            all_links = soup.find_all('a', href=True)
            article_links = []
            
            for link in all_links:
                href = link.get('href', '')
                if 'fullstory.php' in href:
                    text = link.get_text(strip=True)
                    if len(text) > 20:  # Real article titles are longer
                        article_links.append(link)
            
            logger.info(f"  Found {len(article_links)} potential articles")
            
            for link_elem in article_links[:limit * 2]:  # Get more than needed for filtering
                if len(articles) >= limit:
                    break
                
                try:
                    article_data = self._parse_article_link(link_elem)
                    
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
                    logger.error(f"  Error parsing article link: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} English articles from {self.source_name}")
            return articles
            
        except Exception as e:
            logger.error(f"❌ {self.source_name} scraping failed: {e}")
            return []
    
    def _parse_article_link(self, link_elem) -> Optional[dict]:
        """Parse article data from link element"""
        try:
            # Get title from link text
            title = link_elem.get_text(strip=True)
            
            if len(title) < 20:  # Too short to be a real article title
                return None
            
            # Get URL
            url = link_elem.get('href')
            if not url:
                return None
            
            # Make URL absolute
            if not url.startswith('http'):
                base_url = "https://drinksint.com"
                url = base_url + url if url.startswith('/') else f"{base_url}/{url}"
            
            # Find image (optional) - look in parent container
            parent_container = link_elem.find_parent('div') or link_elem.find_parent('td')
            img_elem = None
            if parent_container:
                img_elem = parent_container.select_one('img')
            
            image_url = None
            if img_elem:
                image_url = img_elem.get('src')
                if image_url and not image_url.startswith('http'):
                    if image_url.startswith('//'):
                        image_url = f"https:{image_url}"
                    else:
                        image_url = f"https://drinksint.com{image_url}"
            
            return {
                'title': title,
                'url': url,
                'image_url': image_url,
                'published_date': None  # Date extraction can be added later if needed
            }
            
        except Exception as e:
            logger.error(f"Error parsing article link: {e}")
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
                soup.select_one('.article-body') or
                soup.select_one('.story-body') or
                soup.select_one('.entry-content') or
                soup.select_one('.post-content') or
                soup.select_one('article') or
                soup.select_one('[class*="content"]') or
                soup.select_one('div[class*="story"]')
            )
            
            if not content_elem:
                # Fallback: try to find main content area
                content_elem = soup.find('td', {'class': 'mainContent'})
            
            if not content_elem:
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, .social-share, .related, nav, footer, .comments, .share'):
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
        """Clean scraped text"""
        if not text:
            return ""
        
        # Remove extra whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n\n'.join(lines)
        
        # Remove non-breaking spaces
        text = text.replace('\xa0', ' ')
        text = text.replace('\u200b', '')
        
        # Remove very short lines (likely UI elements)
        lines = text.split('\n\n')
        lines = [line for line in lines if len(line) > 15]
        text = '\n\n'.join(lines)
        
        # Remove multiple spaces
        import re
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
