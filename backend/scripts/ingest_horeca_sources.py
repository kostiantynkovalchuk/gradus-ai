"""
HoReCa Knowledge Ingestion Script
Ingest articles from leading HoReCa industry sources into Pinecone for Maya's RAG system
"""

import sys
import os
import asyncio
import time
import re
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
from bs4 import BeautifulSoup
from pinecone import Pinecone

from services.rag_utils import get_embedding

HORECA_SOURCES = [
    {
        "name": "Restaurant Business Online",
        "base_url": "https://www.restaurantbusinessonline.com",
        "rss_url": "https://www.restaurantbusinessonline.com/rss.xml",
        "category": "restaurant_operations",
        "sector": "restaurant",
        "region": "global",
        "description": "US restaurant trends, franchising, operations"
    },
    {
        "name": "QSR Magazine",
        "base_url": "https://www.qsrmagazine.com",
        "rss_url": "https://www.qsrmagazine.com/rss.xml",
        "category": "fast_casual",
        "sector": "restaurant",
        "region": "global",
        "description": "Fast casual & quick service insights"
    },
    {
        "name": "Hospitality Net",
        "base_url": "https://www.hospitalitynet.org",
        "rss_url": "https://www.hospitalitynet.org/rss/news.xml",
        "category": "hotel_management",
        "sector": "hotel",
        "region": "global",
        "description": "Global hotel industry news"
    },
    {
        "name": "Hotel Management",
        "base_url": "https://www.hotelmanagement.net",
        "rss_url": "https://www.hotelmanagement.net/rss.xml",
        "category": "hotel_operations",
        "sector": "hotel",
        "region": "global",
        "description": "Hotel operations, technology, design"
    },
    {
        "name": "Modern Restaurant Management",
        "base_url": "https://modernrestaurantmanagement.com",
        "rss_url": "https://modernrestaurantmanagement.com/feed/",
        "category": "restaurant_tech",
        "sector": "restaurant",
        "region": "global",
        "description": "Restaurant tech, trends, operations"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}


async def fetch_rss_articles(source: Dict, client: httpx.AsyncClient, limit: int = 15) -> List[Dict]:
    """Fetch article URLs from RSS feed"""
    articles = []
    
    try:
        response = await client.get(source["rss_url"], headers=HEADERS, timeout=30.0)
        
        if response.status_code != 200:
            print(f"  ⚠️ RSS returned {response.status_code}")
            return articles
        
        soup = BeautifulSoup(response.text, 'lxml-xml')
        
        items = soup.find_all('item')[:limit]
        
        for item in items:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubdate_elem = item.find('pubDate')
            desc_elem = item.find('description')
            
            if title_elem and link_elem:
                articles.append({
                    "title": title_elem.get_text(strip=True),
                    "url": link_elem.get_text(strip=True),
                    "published": pubdate_elem.get_text(strip=True) if pubdate_elem else None,
                    "excerpt": desc_elem.get_text(strip=True)[:500] if desc_elem else ""
                })
        
        print(f"  📋 Found {len(articles)} articles in RSS")
        
    except Exception as e:
        print(f"  ❌ RSS fetch error: {e}")
    
    return articles


async def scrape_article_content(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Scrape article content from URL"""
    try:
        response = await client.get(url, headers=HEADERS, timeout=30.0, follow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'noscript']):
            tag.decompose()
        
        content_selectors = [
            'article',
            '.article-content',
            '.article-body',
            '.post-content',
            '.entry-content',
            '.content-body',
            '[itemprop="articleBody"]',
            '.story-body',
            'main'
        ]
        
        content = None
        for selector in content_selectors:
            elem = soup.select_one(selector)
            if elem:
                content = elem.get_text(separator='\n', strip=True)
                break
        
        if not content:
            body = soup.find('body')
            if body:
                content = body.get_text(separator='\n', strip=True)
        
        if content:
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            content = '\n'.join(lines)
            
            content = re.sub(r'\n{3,}', '\n\n', content)
            
            if len(content) > 100:
                return content[:8000]
        
        return None
        
    except Exception as e:
        print(f"    ⚠️ Scrape error: {e}")
        return None


async def ingest_horeca_article(article: Dict, source: Dict, index) -> bool:
    """Ingest a single HoReCa article into Pinecone"""
    try:
        title = article.get('title', 'Untitled')
        content = article.get('content', '')
        url = article.get('url', '')
        
        if not content or len(content) < 100:
            return False
        
        article_text = f"""SOURCE: {source['name']}
CATEGORY: {source['category'].replace('_', ' ').title()}
REGION: {source['region'].title()} (applicable to Ukraine)
SECTOR: {source['sector'].title()}

TITLE: {title}

CONTENT:
{content}

This is industry knowledge from {source['name']}, a leading HoReCa publication,
providing insights for restaurant, hotel, and cafe operators in Ukraine."""
        
        embedding = get_embedding(article_text)
        
        vector_id = f"horeca_{source['sector']}_{hash(url) % 10000000}_{int(datetime.now().timestamp())}"
        
        vector = {
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "text": article_text[:1500],
                "title": title[:200],
                "source": source['name'],
                "source_url": url[:300],
                "category": source['category'],
                "region": source['region'],
                "content_type": "industry_article",
                "is_gradus_content": False,
                "industry_sector": source['sector'],
                "published_date": article.get('published', '')[:50] if article.get('published') else '',
                "relevance": "high",
                "created_at": datetime.now().isoformat()
            }
        }
        
        index.upsert(vectors=[vector], namespace="company_knowledge")
        return True
        
    except Exception as e:
        print(f"    ❌ Ingest error: {e}")
        return False


async def process_source(source: Dict, index, client: httpx.AsyncClient, articles_per_source: int = 12) -> Dict:
    """Process a single HoReCa source"""
    print(f"\n📰 {source['name']}")
    print(f"   {source['description']}")
    
    results = {"total": 0, "success": 0, "failed": 0}
    
    articles = await fetch_rss_articles(source, client, limit=articles_per_source)
    
    if not articles:
        print("  ⚠️ No articles found, trying sitemap...")
        return results
    
    for article in articles:
        results["total"] += 1
        
        print(f"  📄 {article['title'][:60]}...")
        
        await asyncio.sleep(1.5)
        
        content = await scrape_article_content(article['url'], client)
        
        if not content:
            print(f"    ⚠️ Could not extract content")
            results["failed"] += 1
            continue
        
        article['content'] = content
        
        success = await ingest_horeca_article(article, source, index)
        
        if success:
            print(f"    ✅ Ingested")
            results["success"] += 1
        else:
            results["failed"] += 1
    
    return results


async def main():
    """Main ingestion function"""
    print("=" * 60)
    print("🌍 HoReCa Knowledge Ingestion for Maya AI")
    print("=" * 60)
    
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if not pinecone_key:
        print("❌ PINECONE_API_KEY not set!")
        return
    
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("❌ OPENAI_API_KEY not set!")
        return
    
    pc = Pinecone(api_key=pinecone_key)
    index_name = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
    index = pc.Index(index_name)
    
    print(f"✅ Connected to Pinecone index: {index_name}")
    print(f"📚 Processing {len(HORECA_SOURCES)} HoReCa sources...")
    
    total_stats = {"total": 0, "success": 0, "failed": 0}
    
    async with httpx.AsyncClient() as client:
        for source in HORECA_SOURCES:
            try:
                results = await process_source(source, index, client)
                total_stats["total"] += results["total"]
                total_stats["success"] += results["success"]
                total_stats["failed"] += results["failed"]
                
                await asyncio.sleep(3)
                
            except Exception as e:
                print(f"  ❌ Source error: {e}")
    
    print("\n" + "=" * 60)
    print("📊 INGESTION SUMMARY:")
    print(f"   Sources processed: {len(HORECA_SOURCES)}")
    print(f"   Total articles: {total_stats['total']}")
    print(f"   Successfully ingested: {total_stats['success']}")
    print(f"   Failed: {total_stats['failed']}")
    
    if total_stats['success'] > 0:
        print("\n✅ Maya now has HoReCa industry knowledge!")
        print("   She can answer questions about:")
        print("   - Restaurant operations & profitability")
        print("   - Hotel management & guest experience")
        print("   - Kitchen technology & equipment")
        print("   - Labor management & staffing")
        print("   - Menu trends & pricing strategies")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
