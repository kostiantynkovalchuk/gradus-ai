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
        'wine': ['VILLA UA', 'KRISTI VALLEY', 'KOSHER', 'LUIGI ANTONIO', 
                 'VIAGGIO', 'DIDI LARI', 'PEDRO MARTINEZ'],
        'soju': ['FUNJU']
    }
    
    enriched_brands = []
    content_lower = content.lower()
    
    for category, brands in brand_patterns.items():
        for brand in brands:
            if brand.lower() in content_lower:
                if category == 'vodka':
                    context = f"{brand} is a premium vodka brand distributed by {company_name}, one of Ukraine's largest alcohol distributors with 40,000+ retail points. {brand} vodka is part of AVTD's diverse spirits portfolio."
                elif category == 'cognac':
                    context = f"{brand} is a premium cognac brand distributed by {company_name}. {brand} cognac represents AVTD's commitment to quality spirits in the Ukrainian market."
                elif category == 'wine':
                    context = f"{brand} is a wine brand in the portfolio of {company_name}. {brand} wine is distributed through AVTD's extensive network of 40,000+ retail locations across Ukraine."
                elif category == 'soju':
                    context = f"{brand} is a Korean-style soju distributed by {company_name}. {brand} soju represents AVTD's expansion into Asian spirit categories."
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
    
    brands = extract_brands_from_content(content, company_name)
    
    if brands:
        logger.info(f"Found {len(brands)} brands to enrich")
        for brand_info in brands:
            enriched_text = f"""
{brand_info['context']}

About {company_name}:
{company_name} (AVTD) is Ukraine's leading alcohol distributor with direct deliveries to over 40,000 retail locations nationwide. The company specializes in premium spirits, wines, and innovative beverage brands.

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
        
        original_chunks = chunk_text(content)
        
        all_chunks = enriched_chunks + original_chunks
        
        vectors = []
        for i, chunk in enumerate(all_chunks):
            embedding = get_embedding(chunk)
            
            is_enriched = i < len(enriched_chunks)
            chunk_type = "brand" if is_enriched else "original"
            
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
        
        return {
            'status': 'success',
            'message': f"Успішно завантажено {len(all_chunks)} фрагментів з {company_name} ({len(enriched_chunks)} брендів)",
            'company': company_name,
            'chunks_count': len(all_chunks),
            'brand_chunks': len(enriched_chunks),
            'url': url,
            'method': method
        }
        
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        return {
            'status': 'error',
            'message': f"Помилка при обробці: {str(e)}"
        }

async def retrieve_context(query: str, index, top_k: int = 3) -> Tuple[str, List[str]]:
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
            if match.score > 0.45:
                metadata = match.metadata
                contexts.append(metadata.get('text', ''))
                source = f"{metadata.get('company', 'Unknown')} ({metadata.get('url', '')})"
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
