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
                
                article_data = {
                    'source': 'The Spirits Business',
                    'url': article_url,
                    'title': title,
                    'excerpt': excerpt if excerpt else title,
                    'date': date_str,
                    'author': author,
                    'scraped_at': datetime.utcnow().isoformat()
                }
                
                articles.append(article_data)
                logger.info(f"Scraped article: {title[:50]}...")
            
            logger.info(f"Successfully scraped {len(articles)} articles from The Spirits Business")
            return articles
            
        except Exception as e:
            logger.error(f"Error scraping The Spirits Business: {str(e)}")
            raise
    
    def get_article_content(self, url: str) -> Dict:
        """
        Fetch and extract full content from a specific article URL using trafilatura.
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
