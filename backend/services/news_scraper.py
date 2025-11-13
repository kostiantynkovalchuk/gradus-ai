import requests
from bs4 import BeautifulSoup
import trafilatura
from typing import List, Dict
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

class NewsScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def clean_article_content(self, content: str, title: str) -> str:
        """
        Clean article content by removing:
        - Duplicate title at the beginning
        - Author byline (By Author Name)
        - Related news section at the end
        - Extra metadata
        
        Args:
            content: Raw article text
            title: Article title
            
        Returns:
            Clean article content
        """
        if not content:
            return ""
        
        title_escaped = re.escape(title)
        content = re.sub(f'^{title_escaped}\\s*', '', content, flags=re.IGNORECASE)
        
        byline_pattern = r'(?:^|\n)By\s+[A-Z][a-zA-Z\'\-\.]*(?:\s+[A-Z][a-zA-Z\'\-\.]*)*(?=\n|$|[A-Z][a-z]|[A-Z]{2,})'
        content = re.sub(byline_pattern, '\n', content, flags=re.MULTILINE)
        
        content = re.split(r'Related news|Related articles|Related content', content, flags=re.IGNORECASE)[0]
        
        content = re.sub(r'\n\s*\n+', '\n\n', content)
        content = content.strip()
        
        return content
    
    def extract_author(self, content: str) -> str:
        """
        Extract author name from content.
        Handles multi-word names, hyphens, apostrophes, and initials.
        Returns author name or empty string
        """
        byline_pattern = r'(?:^|\n)By\s+([A-Z][a-zA-Z\'\-\.]*(?:\s+[A-Z][a-zA-Z\'\-\.]*)*?)(?=\n|$|[A-Z][a-z]|[A-Z]{2,})'
        match = re.search(byline_pattern, content, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
        return ""
    
    def scrape_spirits_business(self, limit: int = 5) -> List[Dict]:
        """
        Scrape latest articles from The Spirits Business homepage.
        Returns a list of articles with title, URL, excerpt, date, and author.
        """
        articles = []
        
        try:
            logger.info("Scraping The Spirits Business...")
            url = "https://www.thespiritsbusiness.com"
            
            response = requests.get(url, headers=self.headers, timeout=15)
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
                
                title_elem = link.find('strong') or link.find(['h1', 'h2', 'h3'])
                if title_elem:
                    title = title_elem.get_text(strip=True)
                else:
                    title = link.get_text(strip=True)
                
                if not title or len(title) < 10:
                    continue
                
                parent = link.find_parent(['article', 'div', 'li'])
                excerpt = ""
                date_str = ""
                author = ""
                
                if parent:
                    date_elem = parent.find('time') or parent.find(text=re.compile(r'\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}'))
                    if date_elem:
                        date_str = date_elem if isinstance(date_elem, str) else date_elem.get_text(strip=True)
                    
                    author_elem = parent.find(text=re.compile(r'^By\s+'))
                    if author_elem:
                        author = author_elem.strip()
                    
                    for p in parent.find_all(['p', 'div'], limit=3):
                        text = p.get_text(strip=True)
                        if text and len(text) > 50 and 'By ' not in text[:10]:
                            excerpt = text[:300]
                            break
                
                clean_data = self.extract_article_content(article_url)
                raw_content = clean_data.get('content', '')
                article_title = clean_data.get('title') or title
                
                extracted_author = self.extract_author(raw_content)
                if extracted_author:
                    author = extracted_author
                elif author:
                    author = re.sub(r'^By\s+', '', author).strip()
                
                cleaned_content = self.clean_article_content(raw_content, article_title)
                
                article_data = {
                    'source': 'The Spirits Business',
                    'url': article_url,
                    'title': article_title,
                    'summary': cleaned_content[:1000],
                    'content': cleaned_content,
                    'image_url': '',
                    'published_date': date_str,
                    'author': author,
                    'scraped_at': datetime.utcnow().isoformat()
                }
                
                articles.append(article_data)
                logger.info(f"Scraped article: {title[:50]}... ({len(cleaned_content)} chars cleaned)")
            
            logger.info(f"Successfully scraped {len(articles)} articles from The Spirits Business")
            return articles
            
        except Exception as e:
            logger.error(f"Error scraping The Spirits Business: {str(e)}")
            raise
    
    def extract_article_content(self, url: str) -> Dict[str, str]:
        """
        Extract clean article content from URL using Trafilatura.
        Removes metadata like date, author, category.
        
        Returns dict with 'title' and 'content'
        """
        try:
            logger.info(f"Extracting clean content from: {url}")
            
            downloaded = trafilatura.fetch_url(url)
            
            if not downloaded:
                logger.warning(f"Failed to download {url}")
                return {"title": "", "content": ""}
            
            result = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                output_format='json',
                with_metadata=True
            )
            
            if result:
                import json
                data = json.loads(result)
                
                title = data.get('title', '')
                content = data.get('text', '')
                
                logger.info(f"Extracted {len(content)} chars from: {title[:50]}...")
                
                return {
                    "title": title,
                    "content": content
                }
            
            logger.warning(f"No content extracted from {url}")
            return {"title": "", "content": ""}
            
        except Exception as e:
            logger.error(f"Failed to extract content from {url}: {e}")
            return {"title": "", "content": ""}
    
    def get_article_content(self, url: str) -> Dict:
        """
        Fetch and extract full content from a specific article URL using trafilatura.
        (Deprecated - use extract_article_content instead)
        """
        try:
            logger.info(f"Fetching article content from: {url}")
            
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            downloaded = response.content
            
            text_content = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )
            
            metadata = trafilatura.extract_metadata(downloaded)
            
            article_data = {
                'url': url,
                'title': metadata.title if metadata and metadata.title else 'No title',
                'author': metadata.author if metadata and metadata.author else '',
                'date': metadata.date if metadata and metadata.date else '',
                'content': text_content if text_content else '',
                'description': metadata.description if metadata and metadata.description else '',
                'scraped_at': datetime.utcnow().isoformat()
            }
            
            logger.info(f"Successfully extracted content from: {url}")
            return article_data
            
        except Exception as e:
            logger.error(f"Error fetching article content from {url}: {str(e)}")
            raise

news_scraper = NewsScraper()
