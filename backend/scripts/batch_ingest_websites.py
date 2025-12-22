import asyncio
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from services.carousel_scraper import scrape_website_with_carousels
from services.rag_service import add_documents_to_rag

WEBSITES = [
    {"url": "https://avtd.com/", "name": "Best Brands Main", "brand": "Best Brands", "type": "distributor"},
    {"url": "https://www.dovbush.com.ua/", "name": "DOVBUSH", "brand": "DOVBUSH", "type": "cognac"},
    {"url": "https://greendayvodka.com/uk/", "name": "Green Day", "brand": "GREENDAY", "type": "vodka"},
    {"url": "https://villaua.com/", "name": "Villa", "brand": "VILLA", "type": "wine"},
    {"url": "https://helsinki.ua/", "name": "Helsinki", "brand": "HELSINKI", "type": "vodka"},
    {"url": "https://ukrainka.ua/", "name": "UKRAINKA", "brand": "UKRAINKA", "type": "vodka"},
    {"url": "https://wineviaggio.com/", "name": "Wineviaggio", "brand": "WINEVIAGGIO", "type": "wine"},
    {"url": "https://marlinvodka.com/indexUK.html", "name": "Marlin", "brand": "MARLIN", "type": "vodka"},
    {"url": "https://kristivalley.com/", "name": "Kristi Valley", "brand": "KRISTI VALLEY", "type": "wine"},
    {"url": "https://adjari.com.ua/index1.html", "name": "Adjari", "brand": "ADJARI", "type": "cognac"},
    {"url": "https://didilari.com/", "name": "Didi Lari", "brand": "DIDI LARI", "type": "wine"}
]

def enrich_content_with_rebrand(content: str, brand: str) -> str:
    """
    Replace AVTD mentions with Best Brands.
    Websites still say AVTD, but Maya should use Best Brands!
    """
    
    replacements = {
        "AVTD": "Best Brands",
        "АВТД": "Best Brands",
        "АВ ТД": "Best Brands",
        "ТД АВ": "Best Brands",
        "Торговий Дім АВ": "Best Brands",
        "ТД «АВ»": "Best Brands",
        "TD AV": "Best Brands",
        "АВ Group": "Best Brands",
        "BestBrands": "Best Brands",
    }
    
    enriched = content
    for old, new in replacements.items():
        enriched = re.sub(
            re.escape(old), 
            new, 
            enriched, 
            flags=re.IGNORECASE
        )
    
    enrichment = f"""

[COMPANY CONTEXT: {brand} is distributed by Best Brands, Ukraine's largest alcohol distributor with 40,000+ retail points. Best Brands (formerly AVTD) represents premium brands across vodka, cognac, and wine categories.]
"""
    
    return enriched + enrichment

async def scrape_single_website(website_info):
    """Scrape and enrich a single website"""
    print(f"\n🔍 Scraping {website_info['name']} ({website_info['url']})...")
    
    try:
        content = await scrape_website_with_carousels(website_info['url'])
        
        if content:
            enriched_content = enrich_content_with_rebrand(
                content, 
                website_info['brand']
            )
            
            print(f"✅ Scraped {website_info['name']}: {len(content)} chars")
            print(f"   📝 Enriched with Best Brands context")
            
            return {
                "content": enriched_content,
                "metadata": {
                    "source": website_info['url'],
                    "source_type": "company_website",
                    "brand": website_info['brand'],
                    "category": website_info['type'],
                    "company": "Best Brands",
                    "enriched": True,
                    "scraped_at": datetime.now().isoformat()
                }
            }
        else:
            print(f"⚠️ No content from {website_info['name']}")
            return None
            
    except Exception as e:
        print(f"❌ Error scraping {website_info['name']}: {e}")
        return None

async def batch_scrape_websites():
    """Scrape all websites sequentially"""
    print("🚀 Starting batch scraping with rebrand enrichment...")
    print(f"📊 Total websites: {len(WEBSITES)}")
    
    results = []
    for i, website in enumerate(WEBSITES, 1):
        print(f"\n[{i}/{len(WEBSITES)}] Processing {website['name']}...")
        result = await scrape_single_website(website)
        if result:
            results.append(result)
        await asyncio.sleep(3)
    
    print(f"\n📊 Scraped {len(results)}/{len(WEBSITES)} websites successfully")
    return results

def ingest_to_rag(scraped_data):
    """Ingest enriched data to Pinecone"""
    print("\n📤 Ingesting to RAG...")
    
    success_count = 0
    for item in scraped_data:
        try:
            add_documents_to_rag(
                documents=[{
                    "content": item["content"],
                    "metadata": item["metadata"]
                }],
                namespace="company_knowledge"
            )
            print(f"✅ Ingested {item['metadata']['brand']}")
            success_count += 1
            
        except Exception as e:
            print(f"❌ Error ingesting {item['metadata']['brand']}: {e}")
    
    print(f"\n📊 Ingested {success_count}/{len(scraped_data)} successfully")

async def main():
    """Main batch processing"""
    print("=" * 60)
    print("🏭 BATCH WEBSITE INGESTION - BEST BRANDS REBRAND")
    print("=" * 60)
    
    scraped_data = await batch_scrape_websites()
    
    if not scraped_data:
        print("❌ No data scraped")
        return
    
    ingest_to_rag(scraped_data)
    
    print("\n" + "=" * 60)
    print("✅ BATCH INGESTION COMPLETE!")
    print(f"📊 Processed {len(scraped_data)}/{len(WEBSITES)} websites")
    print("🔄 All AVTD mentions replaced with Best Brands")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
