import re
import os
import httpx
import logging
from typing import List, Tuple, Optional
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

async def scrape_website_content(url: str) -> dict:
    """Scrape website content"""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            
            title = soup.title.string if soup.title else ""
            
            paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3', 'li'])
            text_content = ' '.join([p.get_text(strip=True) for p in paragraphs])
            
            text_content = ' '.join(text_content.split())[:5000]
            
            return {
                'url': url,
                'title': title,
                'content': text_content,
                'status': 'success'
            }
    except Exception as e:
        logger.error(f"Failed to scrape {url}: {e}")
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
    """Ingest website content into vector database"""
    try:
        scraped = await scrape_website_content(url)
        
        if scraped['status'] == 'error':
            return {
                'status': 'error',
                'message': f"Не вдалося завантажити сайт: {scraped.get('error', 'Unknown error')}"
            }
        
        content = scraped['content']
        if not content:
            return {
                'status': 'error',
                'message': 'Не знайдено контенту на сторінці'
            }
        
        chunks = chunk_text(content)
        
        vectors = []
        for i, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            
            vectors.append({
                'id': f"{company_name}_{i}",
                'values': embedding,
                'metadata': {
                    'company': company_name,
                    'url': url,
                    'chunk_index': i,
                    'text': chunk[:1000]
                }
            })
        
        index.upsert(vectors=vectors, namespace="company_knowledge")
        
        return {
            'status': 'success',
            'message': f"Успішно завантажено {len(chunks)} фрагментів з {company_name}",
            'company': company_name,
            'chunks_count': len(chunks),
            'url': url
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
            if match.score > 0.5:
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
