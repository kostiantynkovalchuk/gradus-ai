"""
Just Drinks scraper - English source, NEEDS translation
Scrapes lighter, more accessible alcohol news from just-drinks.com
"""

import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Optional
from .base import ScraperBase, ArticlePayload

logger = logging.getLogger(__name__)

class JustDrinksScraper(ScraperBase):
    """Scraper for Just Drinks news (English source)"""
    
    def get_source_name(self) -> str:
        return "Just Drinks"
    
    def get_language(self) -> str:
        return "en"
    
    def get_needs_translation(self) -> bool:
        return True
    
    def scrape_articles(self, limit: int = 5) -> List[ArticlePayload]:
        """Scrape articles from Just Drinks news section"""
        articles = []
        
        try:
            logger.info(f"🔍 Scraping {self.source_name} (English)...")
            news_url = "https://www.just-drinks.com/news/"
            
            headers = {'User-Agent': self.user_agent}
            response = requests.get(news_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article cards
            article_elements = (
                soup.select('article') or
                soup.select('.article-card') or
                soup.select('.news-item') or
                soup.select('.post') or
                soup.select('[class*="article"]')
            )
            
            logger.info(f"  Found {len(article_elements)} potential articles")
            
            for element in article_elements[:limit * 2]:
                if len(articles) >= limit:
                    break
                
                try:
                    article_data = self._parse_article_card(element)
                    
                    if not article_data:
                        continue
                    
                    # Fetch full article content (pass title for cleaning)
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
                            author=article_data.get('author'),
                            image_url=article_data.get('image_url')
                        )
                        articles.append(article)
                        logger.info(f"  ✅ {article_data['title'][:50]}...")
                        
                except Exception as e:
                    logger.error(f"  Error parsing article element: {e}")
                    continue
            
            logger.info(f"✅ Scraped {len(articles)} English articles from {self.source_name}")
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
                element.select_one('.article-title') or
                element.select_one('.headline') or
                element.select_one('[class*="title"]')
            )
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            
            if len(title) < 10:
                return None
            
            # Find the article link - need to be careful to get the actual article URL
            # not the category link (/news/)
            url = None
            
            # Strategy 1: Check if title element is inside a link
            link_elem = title_elem.find_parent('a')
            if link_elem:
                href = link_elem.get('href', '')
                # Make sure it's not just the category page
                if href and '/news/' in href and href.rstrip('/') != 'https://www.just-drinks.com/news' and href != '/news/':
                    url = href
            
            # Strategy 2: Check for link inside the title element
            if not url:
                link_inside = title_elem.select_one('a')
                if link_inside:
                    href = link_inside.get('href', '')
                    if href and '/news/' in href and href.rstrip('/') != 'https://www.just-drinks.com/news' and href != '/news/':
                        url = href
            
            # Strategy 3: Look for article links in the card element
            if not url:
                all_links = element.select('a[href]')
                for link in all_links:
                    href = link.get('href', '')
                    # Skip category links, author links, etc.
                    if not href:
                        continue
                    if href == '/news/' or href.rstrip('/') == 'https://www.just-drinks.com/news':
                        continue
                    if '/author/' in href:
                        continue
                    # This looks like an article link
                    if '/news/' in href and len(href) > len('/news/') + 5:
                        url = href
                        break
            
            if not url:
                return None
            
            # Make URL absolute
            if not url.startswith('http'):
                base_url = "https://www.just-drinks.com"
                url = base_url + url if url.startswith('/') else f"{base_url}/{url}"
            
            # Find image (optional)
            img_elem = element.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    if image_url.startswith('//'):
                        image_url = f"https:{image_url}"
                    else:
                        image_url = f"https://www.just-drinks.com{image_url}"
            
            # Find date (optional)
            date_elem = element.select_one('.date') or element.select_one('time') or element.select_one('.published') or element.select_one('.post-date')
            published_date = None
            if date_elem:
                published_date = date_elem.get_text(strip=True)
                if not published_date and date_elem.has_attr('datetime'):
                    published_date = date_elem['datetime']
            
            # Find author (optional)
            author_elem = element.select_one('.author') or element.select_one('.byline')
            author = None
            if author_elem:
                author = author_elem.get_text(strip=True)
            
            return {
                'title': title,
                'url': url,
                'image_url': image_url,
                'published_date': published_date,
                'author': author
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
            
            # Extended list of content selectors - try in order of specificity
            content_selectors = [
                '[itemprop="articleBody"]',    # Schema.org markup (most reliable)
                '.article-body',                # Main article content
                '.article__body',               # Alternative naming
                '.story-body',                  # News story body
                '.full-article',                # Full article container
                '.article-content',             # Article content class
                '.entry-content',               # WordPress style
                '.post-content',                # Post body
                '.content-body',                # Content body
                'article .content',             # Article content wrapper
                '[class*="article-body"]',      # Partial match
                '[class*="story-content"]',     # Story content
                'article',                      # Fallback to article tag
            ]
            
            content_elem = None
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    # Check if this has substantial content
                    text_len = len(content_elem.get_text(strip=True))
                    if text_len > 100:
                        logger.debug(f"  Using selector: {selector} ({text_len} chars)")
                        break
                    else:
                        content_elem = None  # Too short, try next selector
            
            if not content_elem:
                # Fallback: try trafilatura for clean extraction
                try:
                    import trafilatura
                    downloaded = trafilatura.fetch_url(url)
                    if downloaded:
                        content = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
                        if content and len(content) > 100:
                            logger.info(f"  Used trafilatura for content extraction")
                            return self._clean_content(content, title)
                except Exception as e:
                    logger.debug(f"  Trafilatura fallback failed: {e}")
                
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements (ads, scripts, social, etc.)
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, .social-share, .related-articles, nav, footer, .comments, .share, .newsletter, .subscription, .promo'):
                unwanted.decompose()
            
            # Remove metadata elements BEFORE extracting text
            metadata_selectors = [
                '.author', '.post-author', '.byline', '.article-author',
                '.date', '.post-date', '.published-date', '.timestamp', 'time',
                '.article-meta', '.meta', '.post-meta', '.entry-meta',
                '.social-share', '.share-buttons', '.share-links',
                '.tags', '.post-tags', '.article-tags',
                '.article-teaser', '.teaser', '.preview', '.excerpt'
            ]
            for selector in metadata_selectors:
                for element in content_elem.select(selector):
                    element.decompose()
            
            # Extract all paragraph text for better content capture
            paragraphs = content_elem.select('p')
            if paragraphs and len(paragraphs) > 2:
                # Use paragraph-based extraction for better quality
                content_parts = []
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if text and len(text) > 20:  # Skip very short paragraphs
                        content_parts.append(text)
                content = '\n\n'.join(content_parts)
            else:
                # Fallback to full text extraction
                content = content_elem.get_text(separator='\n', strip=True)
            
            # Check content length and warn if too short
            if len(content) < 200:
                logger.warning(f"  Just Drinks article too short ({len(content)} chars): {title[:50]}...")
                # Try trafilatura as fallback
                try:
                    import trafilatura
                    downloaded = trafilatura.fetch_url(url)
                    if downloaded:
                        traf_content = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
                        if traf_content and len(traf_content) > len(content):
                            logger.info(f"  Trafilatura recovered more content: {len(traf_content)} chars")
                            content = traf_content
                except Exception:
                    pass
            
            # Clean content (remove metadata patterns, fix formatting)
            content = self._clean_content(content, title)
            
            return content
            
        except Exception as e:
            logger.error(f"Error fetching content from {url}: {e}")
            return None
    
    def _clean_content(self, content: str, title: str) -> str:
        """Clean Just Drinks article content - remove author, dates, fix formatting"""
        import re
        
        if not content:
            return ""
        
        # Remove duplicate title if present at start (within first 500 chars)
        if title and len(title) > 15:
            if content.startswith(title):
                content = content[len(title):].strip()
            else:
                title_pos = content[:500].find(title)
                if title_pos >= 0:
                    content = content[:title_pos] + content[title_pos + len(title):]
                    content = content.strip()
        
        # Split into lines
        lines = content.split('\n')
        cleaned_lines = []
        
        # English month names for date detection
        months = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip "By <Author>" bylines (e.g., "By Fiona Holland", "By John Smith in News")
            if re.match(r'^By\s+[A-Z][a-z]+(\s+[A-Z][a-z\-]+)*(\s+(in|for|at|from)\s+.*)?$', line, re.IGNORECASE):
                continue
            
            # Skip author names (2-4 capitalized words, short line, no punctuation)
            words = line.split()
            if 1 <= len(words) <= 4 and len(line) < 40:
                # Check if it looks like an author name (capitalized words, allowing small connectors)
                name_words = [w for w in words if len(w) > 2]  # Ignore small words like "in", "at"
                if name_words and all(w[0].isupper() for w in name_words if w and w[0].isalpha()):
                    # But don't skip if it ends with punctuation (likely a sentence)
                    if not line.endswith(('.', '!', '?', ':')):
                        continue
            
            # Skip date patterns: "November 24, 2025", "24 November 2025", etc.
            if re.match(rf'^{months}\s+\d{{1,2}},?\s+\d{{4}}$', line, re.IGNORECASE):
                continue
            if re.match(rf'^\d{{1,2}}\s+{months},?\s+\d{{4}}$', line, re.IGNORECASE):
                continue
            if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', line):
                continue
            if re.match(r'^\d{4}-\d{2}-\d{2}$', line):
                continue
            
            # Skip very short lines that are likely navigation/UI (but keep source tag)
            if len(line) < 10 and not line.endswith('.') and 'Just Drinks' not in line:
                continue
            
            # Skip social sharing text
            if any(social in line.lower() for social in ['share this', 'tweet', 'linkedin', 'facebook', 'email this']):
                if len(line) < 30:
                    continue
            
            # Skip Just Drinks promotional/subscription content
            promo_phrases = [
                'stay ahead with unbiased news',
                'combine business intelligence and editorial excellence',
                'as a trusted provider of data and insights',
                'gain a deeper understanding of the drinks industry',
                'ready to stay informed',
                'subscribeto',  # No space version
                'subscribe to',
                'the gold standard of business intelligence',
                'reach engaged professionals across',
                'leading media platforms',
                'unique thought leadership and analysis',
                'priorities shaping the profession',
                'just drinks collaborates closely with industry leaders',
                'sign up for our newsletter',
                'get the latest news delivered',
                'unlock exclusive content',
                'already a subscriber',
                'sign into access your account',
                'complete this form',
                'request more information',
                'representative will be in touch',
                'don\'t let policy changes catch you',
                'stay proactive with real-time data',
                'gain the recognition you deserve',
                'just drinks excellence awards',
                'celebrate innovation, leadership',
                'elevate your industry profile',
                'showcase your achievements',
            ]
            line_lower = line.lower()
            if any(phrase in line_lower for phrase in promo_phrases):
                continue
            
            cleaned_lines.append(line)
        
        # Join with double newline for paragraph separation
        content = '\n\n'.join(cleaned_lines)
        
        # Fix paragraph spacing at sentence boundaries (for run-on text)
        content = re.sub(r'\.(\s*)([A-Z])', r'.\n\n\2', content)
        
        # Remove excessive newlines
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
