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
                    
                    # Fetch full article content (pass title for duplicate removal)
                    content = self._fetch_article_content(article_data['url'], article_data['title'])
                    
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
            
            # Remove merged category/metadata prefixes
            title = title.replace('АктуальноАктуально', '').strip()
            title = title.replace('Актуально', '').strip()
            
            # Remove "Новини компаній" and similar prefixes (with or without space)
            import re
            title = re.sub(r'^Новин[иі]\s*компаній\s*', '', title).strip()
            title = re.sub(r'^Новини\s*', '', title).strip()
            title = re.sub(r'^Категорія\s*', '', title).strip()
            
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
    
    def _fetch_article_content(self, url: str, title: str = "") -> Optional[str]:
        """Fetch full article content from article page"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try multiple selectors for article content (delo.ua specific first)
            content_elem = (
                soup.select_one('.c-post__content') or  # Delo.ua specific - most accurate
                soup.select_one('.c-post__body') or     # Delo.ua fallback
                soup.select_one('.article-content') or
                soup.select_one('.post-content') or
                soup.select_one('.entry-content') or
                soup.select_one('.article-body') or
                soup.select_one('[class*="post__content"]')  # Avoid generic 'article' tag
            )
            
            if not content_elem:
                logger.warning(f"  Could not find content container for: {url}")
                return None
            
            # Remove unwanted elements (ads, scripts, social, etc.)
            for unwanted in content_elem.select('script, style, aside, .ads, .advertisement, .related, .comments, .share, .social'):
                unwanted.decompose()
            
            # Remove metadata elements BEFORE extracting text
            metadata_selectors = [
                '.article-meta', '.meta', '.metadata', '.post-meta', '.entry-meta',
                '.category', '.post-category', '.article-category',
                '.date', '.post-date', '.published-date', '.article-date',
                '.author', '.post-author', '.article-author',
                '.tags', '.post-tags', '.article-tags',
                'time', '.time', '.timestamp'
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
        """Clean Delo.ua content with aggressive line joining to fix chaotic breaks"""
        import re
        
        if not content:
            return ""
        
        # Step 1: Remove merged category pattern at very start
        # Pattern: "Новини компанійTitle" or "Новині компанійTitle" (typo variant)
        content = re.sub(r'^Новин[иі] компаній\s*' + re.escape(title) if title else '', title if title else '', content)
        content = re.sub(r'^Новин[иі] компаній\s*', '', content)
        
        # Step 2: Remove metadata patterns
        metadata_patterns = [
            r'^Категорія\s*\n\s*[^\n]*\n',
            r'^Дата публікації\s*\n\s*[^\n]*\n',
            r'^Новини\s*\n',
            r'^\d{1,2}\s+\w+\s+\d{2}:\d{2}\s*\n',
            r'^\d{1,2}\s+(січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)\s+\d{2}:\d{2}\s*\n',
            r'^\d{1,2}\.\d{1,2}\.\d{4}\s*\n',
            r'Змінити мову.*?\n',
            r'Читать на русском.*?\n',
            r'^Автор:?\s*[^\n]*\n',
            r'^Джерело:?\s*[^\n]*\n',
            r'^Фото:?\s*[^\n]*\n',
        ]
        
        for pattern in metadata_patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE | re.IGNORECASE)
        
        # Words/phrases to skip as standalone lines (metadata/UI)
        skip_words = {
            'Категорія', 'Новини', 'Новини компаній', 'Новині компаній',
            'Дата публікації', 'Автор', 'Джерело', 'Фото', 'Теги', 
            'Читайте також', 'Поділитися', 'Share', 'Facebook', 'Twitter', 
            'Telegram', 'Viber', 'Змінити мову', 'Читать на русском', 
            'Читати українською', 'Коментарі', 'Підписатися', 'Реклама', 
            'Більше новин', 'Популярне', 'Актуально'
        }
        
        # Step 3: Get all lines, remove metadata, COMPLETELY REMOVE duplicate titles
        # Title is added separately during posting, so we remove ALL occurrences from content
        lines = content.split('\n')
        filtered_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            
            # Skip empty lines
            if not line_stripped:
                continue
            
            # Skip metadata words
            if line_stripped in skip_words:
                continue
            
            # Skip lines containing only metadata
            skip_line = False
            for skip_word in skip_words:
                if skip_word in line_stripped and len(line_stripped) < 60:
                    skip_line = True
                    break
            if skip_line:
                continue
            
            # Skip date-only lines
            if re.match(r'^\d{1,2}\s+\w+\s+\d{2}:\d{2}$', line_stripped):
                continue
            
            # Skip very short non-sentence lines
            if len(line_stripped) < 8 and not line_stripped.endswith(('.', '!', '?', '"', '»')):
                continue
            
            # REMOVE ALL occurrences of the exact title (title is added separately during posting)
            if title and line_stripped == title:
                continue
            
            filtered_lines.append(line_stripped)
        
        # Step 4: AGGRESSIVE LINE JOINING - join ALL lines into single text block
        full_text = ' '.join(filtered_lines)
        
        # Step 4.5: Remove title if it appears at the very start of content
        # This handles cases like "Title Цьогорічна..." where title is merged with first sentence
        if title and full_text.startswith(title):
            full_text = full_text[len(title):].lstrip()
        
        # Step 4.6: Remove image captions (pattern: "Caption text / Photo credit")
        # Only remove when it's clearly a standalone caption, not inline mention
        # Pattern must be: short caption (no punctuation) + " / " + credit at END of caption
        # This avoids matching legitimate sentences like "За даними Reuters / AFP..."
        photo_credits = ['Depositphotos', 'Getty Images', 'Unsplash', 'УНІАН', 'UNIAN', 'Shutterstock', 'iStock', 'Freepik', 'Freepic']
        for credit in photo_credits:
            # Only match at the very start: "Caption / Credit " followed by capital letter
            # This targets patterns like "Індекс самопочуття ритейлу зріс / Depositphotos Індекс..."
            caption_pattern = f'^[А-ЯІЇЄҐа-яіїєґA-Za-z0-9\\s]{{5,60}}\\s*/\\s*{re.escape(credit)}\\s+(?=[А-ЯІЇЄҐA-Z])'
            full_text = re.sub(caption_pattern, '', full_text, flags=re.IGNORECASE)
        
        # Step 5: Fix spacing issues
        full_text = full_text.replace('\xa0', ' ')
        full_text = full_text.replace('\u200b', '')
        full_text = re.sub(r'  +', ' ', full_text)
        
        # Fix spacing around quotes
        full_text = re.sub(r'\s+"', ' "', full_text)
        full_text = re.sub(r'"\s+', '" ', full_text)
        full_text = re.sub(r'\s+«', ' «', full_text)
        full_text = re.sub(r'»\s+', '» ', full_text)
        
        # Step 6: Rebuild paragraph structure at proper sentence boundaries
        # After quote + attribution + punctuation
        full_text = re.sub(r'([.!?][»"]\s*,?\s*)([A-ZА-ЯІЇЄҐ])', r'\1\n\n\2', full_text)
        
        # After period/question/exclamation + space + capital letter
        full_text = re.sub(r'([.!?]\s+)([A-ZА-ЯІЇЄҐ][а-яіїєґa-z])', r'\1\n\n\2', full_text)
        
        # Before section headers (capital word + colon)
        full_text = re.sub(r'\.(\s+)([А-ЯІЇЄҐ][^\n]{10,80}:)', r'.\n\n\2', full_text)
        
        # Step 7: Group into reasonable paragraphs (2-3 sentences each)
        paragraphs = full_text.split('\n\n')
        grouped_paragraphs = []
        current_group = []
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            current_group.append(para)
            
            # Create paragraph break after 2 sentences or if long enough
            total_len = sum(len(p) for p in current_group)
            if len(current_group) >= 2 or total_len > 350:
                grouped_paragraphs.append(' '.join(current_group))
                current_group = []
        
        # Add remaining
        if current_group:
            grouped_paragraphs.append(' '.join(current_group))
        
        full_text = '\n\n'.join(grouped_paragraphs)
        
        # Step 8: Clean up
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)
        full_text = re.sub(r'  +', ' ', full_text)
        
        # Step 9: Remove trailing incomplete sentences
        lines = full_text.split('\n')
        if lines:
            last_line = lines[-1].strip()
            if len(last_line) < 50 and not last_line.endswith(('.', '!', '?', '"', '»', ')')):
                lines = lines[:-1]
        
        full_text = '\n'.join(lines)
        
        return full_text.strip()
    
    def _clean_text(self, text: str) -> str:
        """Legacy method - redirects to _clean_content"""
        return self._clean_content(text, "")
