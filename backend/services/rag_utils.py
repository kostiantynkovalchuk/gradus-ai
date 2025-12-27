import re
import os
import httpx
import logging
from typing import List, Tuple, Optional, Dict
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from openai import OpenAI

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_embedding(text: str) -> List[float]:
    """Get embedding using OpenAI text-embedding-3-small"""
    try:
        text = text[:8000]
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        raise

def extract_urls(text: str) -> List[str]:
    """Extract URLs from text"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return urls

def is_ingestion_request(text: str) -> bool:
    """Check if message is asking to learn/ingest a website"""
    ingestion_keywords = [
        "вивчи", "вивч", "навчи", "learn", "ingest", 
        "прочитай", "проаналізуй", "analyze", "read",
        "додай", "add", "імпортуй", "import"
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in ingestion_keywords)

def extract_company_name_from_url(url: str) -> str:
    """Extract company name from URL"""
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    company_name = domain.split('.')[0]
    return company_name.upper()

def extract_brands_from_content(content: str, company_name: str) -> List[Dict]:
    """Extract brand names and create rich contextual descriptions."""
    brand_patterns = {
        'vodka': ['GREENDAY', 'HELSINKI', 'MARLIN', 'UKRAINKA'],
        'cognac': ['ADJARI', 'DOVBUSH'],
        'wine': ['VILLA', 'KRISTI VALLEY', 'DIDI LARI', 'WINEVIAGGIO', 'ADJARI'],
        'soju': ['FUNJU']
    }
    
    enriched_brands = []
    content_lower = content.lower()
    
    for category, brands in brand_patterns.items():
        for brand in brands:
            if brand.lower() in content_lower:
                if category == 'vodka':
                    context = f"{brand} is a premium vodka brand distributed by {company_name}, one of Ukraine's largest alcohol distributors with 40,000+ retail points. {brand} vodka is part of Best Brands's diverse spirits portfolio."
                elif category == 'cognac':
                    context = f"{brand} is a premium cognac brand distributed by {company_name}. {brand} cognac represents Best Brands's commitment to quality spirits in the Ukrainian market."
                elif category == 'wine':
                    context = f"{brand} is a wine brand in the portfolio of {company_name}. {brand} wine is distributed through Best Brands's extensive network of 40,000+ retail locations across Ukraine."
                elif category == 'soju':
                    context = f"{brand} is a Korean-style soju distributed by {company_name}. {brand} soju represents Best Brands's expansion into Asian spirit categories."
                else:
                    context = f"{brand} is a brand distributed by {company_name}."
                
                enriched_brands.append({
                    'name': brand,
                    'category': category,
                    'context': context
                })
    
    return enriched_brands

def enrich_company_content(content: str, company_name: str, url: str) -> List[str]:
    """Transform raw scraped content into rich, searchable brand descriptions."""
    enriched_chunks = []
    
    single_brand_patterns = {
        'dovbush': ('DOVBUSH', 'cognac', 'DOVBUSH is a premium Ukrainian cognac brand known for quality and tradition. The brand represents authentic Ukrainian craftsmanship in cognac production.'),
        'greenday': ('GREENDAY', 'vodka', 'GREENDAY is a premium vodka brand with modern positioning and eco-conscious values.'),
        'helsinki': ('HELSINKI', 'vodka', 'HELSINKI is a premium vodka brand inspired by Nordic purity and quality.'),
        'marlin': ('MARLIN', 'vodka', 'MARLIN is a premium vodka brand known for smooth taste and quality.'),
        'adjari': ('ADJARI', 'cognac', 'ADJARI is a premium Georgian-style cognac brand with rich heritage.'),
    }
    
    url_lower = url.lower()
    for pattern, (brand_name, category, description) in single_brand_patterns.items():
        if pattern in url_lower:
            enriched_text = f"""
{description}

About {brand_name}:
{brand_name} is featured on their official website at {url}. As a {category} brand, {brand_name} represents quality and expertise in the Ukrainian spirits market.

Brand: {brand_name}
Category: {category.title()}
Official Website: {url}

Additional Information:
{content[:500]}
            """.strip()
            
            enriched_chunks.append(enriched_text)
            logger.info(f"Detected single-brand site: {brand_name}")
            return enriched_chunks
    
    brands = extract_brands_from_content(content, company_name)
    
    if brands:
        logger.info(f"Found {len(brands)} brands to enrich")
        for brand_info in brands:
            enriched_text = f"""
{brand_info['context']}

About {company_name}:
{company_name} (Best Brands) is Ukraine's leading alcohol distributor with direct deliveries to over 40,000 retail locations nationwide. The company specializes in premium spirits, wines, and innovative beverage brands.

Brand: {brand_info['name']}
Category: {brand_info['category'].title()}
Distributor: {company_name}
Website: {url}
            """.strip()
            
            enriched_chunks.append(enriched_text)
    
    return enriched_chunks

async def scrape_website_content(url: str) -> dict:
    """Scrape website content - tries httpx first, falls back to Playwright for JS sites"""
    try:
        logger.info(f"Scraping {url} with httpx...")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
                tag.decompose()
            
            title = soup.title.string if soup.title else ""
            
            paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3', 'li', 'span', 'div'])
            text_content = ' '.join([p.get_text(strip=True) for p in paragraphs])
            text_content = ' '.join(text_content.split())[:5000]
            
            if len(text_content.strip()) > 100:
                logger.info(f"httpx loaded {len(text_content)} chars from {url}")
                return {
                    'url': url,
                    'title': title,
                    'content': text_content,
                    'status': 'success',
                    'method': 'httpx'
                }
            
            logger.info(f"httpx got insufficient content ({len(text_content)} chars), trying Playwright...")
            
    except Exception as e:
        logger.warning(f"httpx failed for {url}: {e}, trying Playwright...")
    
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            
            title = await page.title()
            
            text_content = await page.evaluate('''() => {
                const scripts = document.querySelectorAll('script, style, noscript, nav, footer, header');
                scripts.forEach(s => s.remove());
                return document.body.innerText || document.body.textContent || '';
            }''')
            
            await browser.close()
            
            text_content = ' '.join(text_content.split())[:5000]
            
            logger.info(f"Playwright loaded {len(text_content)} chars from {url}")
            
            if len(text_content.strip()) < 100:
                return {
                    'url': url,
                    'title': '',
                    'content': '',
                    'status': 'error',
                    'error': 'Не знайдено контенту на сторінці'
                }
            
            return {
                'url': url,
                'title': title,
                'content': text_content,
                'status': 'success',
                'method': 'playwright'
            }
            
    except Exception as e:
        logger.error(f"Playwright also failed for {url}: {e}")
        return {
            'url': url,
            'title': '',
            'content': '',
            'status': 'error',
            'error': str(e)
        }

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks"""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    
    return chunks

async def ingest_website(url: str, company_name: str, index) -> dict:
    """Ingest website content into vector database with brand enrichment"""
    try:
        logger.info(f"Starting ingestion of {url}...")
        scraped = await scrape_website_content(url)
        
        if scraped['status'] == 'error':
            return {
                'status': 'error',
                'message': f"Не вдалося завантажити сайт: {scraped.get('error', 'Unknown error')}"
            }
        
        content = scraped['content']
        if not content or len(content.strip()) < 100:
            return {
                'status': 'error',
                'message': 'Не знайдено контенту на сторінці'
            }
        
        method = scraped.get('method', 'unknown')
        logger.info(f"Successfully scraped {len(content)} chars using {method}")
        
        enriched_chunks = enrich_company_content(content, company_name, url)
        logger.info(f"Created {len(enriched_chunks)} enriched brand documents")
        
        product_chunks = []
        section_chunks = []
        
        logger.info("🌐 Starting full website scrape (all sections)...")
        try:
            from services.carousel_scraper import scrape_full_website, create_product_enrichment
            
            full_site_data = await scrape_full_website(url, company_name)
            
            if full_site_data.get('sections'):
                for section_name, section_data in full_site_data['sections'].items():
                    if section_data.get('text') and len(section_data['text']) > 100:
                        section_chunks.append(f"=== {section_name.upper()} ===\n{section_data['text'][:2000]}")
                logger.info(f"✅ Scraped {len(section_chunks)} website sections")
            
            if full_site_data.get('products'):
                logger.info(f"✅ Extracted {len(full_site_data['products'])} products")
                
                product_text = create_product_enrichment(
                    full_site_data['products'], 
                    company_name,
                    company_name,
                    url
                )
                
                if product_text:
                    product_chunks.append(product_text)
                    logger.info(f"✅ Added product catalog enrichment")
                    
        except Exception as e:
            logger.warning(f"Full site scraping failed (non-fatal): {e}")
        
        original_chunks = chunk_text(content)
        
        all_chunks = enriched_chunks + product_chunks + section_chunks + original_chunks
        
        vectors = []
        for i, chunk in enumerate(all_chunks):
            embedding = get_embedding(chunk)
            
            if i < len(enriched_chunks):
                chunk_type = "brand"
            elif i < len(enriched_chunks) + len(product_chunks):
                chunk_type = "product"
            elif i < len(enriched_chunks) + len(product_chunks) + len(section_chunks):
                chunk_type = "section"
            else:
                chunk_type = "original"
            
            vectors.append({
                'id': f"{company_name}_{chunk_type}_{i}",
                'values': embedding,
                'metadata': {
                    'company': company_name,
                    'url': url,
                    'chunk_index': i,
                    'chunk_type': chunk_type,
                    'text': chunk[:1000]
                }
            })
        
        index.upsert(vectors=vectors, namespace="company_knowledge")
        
        products_info = f", {len(product_chunks)} продуктів" if product_chunks else ""
        sections_info = f", {len(section_chunks)} секцій" if section_chunks else ""
        return {
            'status': 'success',
            'message': f"Успішно завантажено {len(all_chunks)} фрагментів з {company_name} ({len(enriched_chunks)} брендів{products_info}{sections_info})",
            'company': company_name,
            'chunks_count': len(all_chunks),
            'brand_chunks': len(enriched_chunks),
            'product_chunks': len(product_chunks),
            'section_chunks': len(section_chunks),
            'url': url,
            'method': method
        }
        
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        return {
            'status': 'error',
            'message': f"Помилка при обробці: {str(e)}"
        }

async def retrieve_context(query: str, index, top_k: int = 15) -> Tuple[str, List[str]]:
    """Retrieve relevant context from vector database"""
    try:
        query_embedding = get_embedding(query)
        
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            namespace="company_knowledge"
        )
        
        if not results.matches:
            return "", []
        
        contexts = []
        sources = []
        
        for match in results.matches:
            if match.score > 0.40:
                metadata = match.metadata
                contexts.append(metadata.get('text', ''))
                source = f"{metadata.get('company', 'Unknown')} ({metadata.get('source', '')})"
                if source not in sources:
                    sources.append(source)
        
        if not contexts:
            return "", []
        
        combined_context = "\n\n".join(contexts)
        rag_prompt = f"""КОНТЕКСТ З БАЗИ ЗНАНЬ:
{combined_context}

ДЖЕРЕЛА: {', '.join(sources)}"""
        
        return rag_prompt, sources
        
    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        return "", []


async def ingest_article(article, index):
    """
    Ingest a scraped article into Pinecone for RAG knowledge
    
    Args:
        article: ContentQueue database object with title, content, category, etc.
        index: Pinecone index instance
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        content = article.translated_text or article.content or ''
        if not content or len(content.strip()) < 100:
            logger.warning(f"Article #{article.id} too short, skipping ingestion")
            return False
        
        title = article.translated_title or article.title or 'No title'
        
        article_text = f"""TITLE: {title}

CATEGORY: {article.category or 'Industry News'}

SUMMARY: {content[:500]}

FULL CONTENT:
{content}

SOURCE: {article.source or 'Unknown'}
SOURCE URL: {article.source_url or 'N/A'}
PUBLISHED: {article.published_at}
LANGUAGE: {article.language or 'uk'}

This is a news article published by Gradus Media, covering trends, news, and insights in the alcohol and HoReCa industry."""
        
        embedding = get_embedding(article_text)
        
        from datetime import datetime
        vector = {
            "id": f"article_{article.id}_{int(datetime.now().timestamp())}",
            "values": embedding,
            "metadata": {
                "text": article_text[:1000],
                "article_id": str(article.id),
                "title": title[:200],
                "category": article.category or "general",
                "source": (article.source[:100] if article.source else "Unknown"),
                "source_url": (article.source_url[:200] if article.source_url else ""),
                "published_at": str(article.published_at),
                "language": article.language or "uk",
                "content_type": "news_article",
                "is_gradus_content": True,
                "gradus_media_url": f"https://gradusmedia.org/article/{article.id}",
                "created_at": datetime.now().isoformat()
            }
        }
        
        index.upsert(vectors=[vector], namespace="company_knowledge")
        
        logger.info(f"✅ Article ingested: #{article.id} '{title[:50]}...'")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to ingest article #{article.id}: {e}", exc_info=True)
        return False


async def ingest_existing_articles(db_session, index, limit: int = 50):
    """
    Ingest existing approved articles from database
    
    Use this to backfill Pinecone with already-published articles
    
    Args:
        db_session: SQLAlchemy session
        index: Pinecone index
        limit: Max articles to ingest (default 50, prevents overload)
    """
    from models.content import ContentQueue
    
    try:
        articles = db_session.query(ContentQueue).filter(
            ContentQueue.status == 'posted'
        ).order_by(
            ContentQueue.published_at.desc()
        ).limit(limit).all()
        
        logger.info(f"📚 Starting backfill: {len(articles)} articles")
        
        success_count = 0
        for article in articles:
            result = await ingest_article(article, index)
            if result:
                success_count += 1
        
        logger.info(f"✅ Backfill complete: {success_count}/{len(articles)} articles ingested")
        return {
            "total": len(articles),
            "success": success_count,
            "failed": len(articles) - success_count
        }
        
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        return {"error": str(e)}
