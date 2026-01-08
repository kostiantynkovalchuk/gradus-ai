import asyncio
import os
import re
import sys
from datetime import datetime
from unidecode import unidecode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from services.carousel_scraper import scrape_full_website
from services.rag_utils import chunk_text, get_embedding
from pinecone import Pinecone


def sanitize_vector_id(text: str) -> str:
    """
    Convert text to ASCII-safe string for Pinecone vector IDs.
    Handles Ukrainian/Cyrillic characters.
    """
    ascii_text = unidecode(text)
    ascii_text = ascii_text.replace(' ', '_')
    ascii_text = re.sub(r'[^a-zA-Z0-9_-]', '', ascii_text)
    if len(ascii_text) > 50:
        ascii_text = ascii_text[:50]
    return ascii_text


def ingest_scraped_content_to_pinecone(content: str, product_sections: list, metadata: dict):
    """
    Ingest content with SPECIAL handling for product data.
    Product sections get priority metadata tagging.
    """
    
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))
    
    vectors_to_upsert = []
    
    if product_sections:
        print(f"   🎯 Processing {len(product_sections)} PRODUCT sections...")
        
        for prod_section in product_sections:
            enriched_product = enrich_content_with_rebrand(
                prod_section['text'], 
                metadata['brand']
            )
            
            product_chunks = chunk_text(enriched_product, chunk_size=500, overlap=50)
            
            for i, chunk in enumerate(product_chunks):
                try:
                    embedding = get_embedding(chunk)
                    timestamp = datetime.now().timestamp()
                    safe_section_name = sanitize_vector_id(prod_section['name'])
                    safe_brand = sanitize_vector_id(metadata['brand'])
                    vector_id = f"{safe_brand}_PRODUCT_{safe_section_name}_{i}_{int(timestamp)}"
                    
                    vector = {
                        "id": vector_id,
                        "values": embedding,
                        "metadata": {
                            **metadata,
                            "text": chunk,
                            "chunk_index": i,
                            "content_type": "PRODUCT",
                            "section_name": prod_section['name'],
                            "is_product_info": True,
                            "section_url": prod_section.get('url', '')
                        }
                    }
                    vectors_to_upsert.append(vector)
                    
                except Exception as e:
                    print(f"   ⚠️ Error with product chunk {i}: {e}")
            
            print(f"      ✅ {prod_section['name']}: {len(product_chunks)} chunks")
    
    print(f"   📄 Processing general content...")
    general_chunks = chunk_text(content, chunk_size=500, overlap=50)
    
    for i, chunk in enumerate(general_chunks):
        try:
            embedding = get_embedding(chunk)
            timestamp = datetime.now().timestamp()
            safe_brand = sanitize_vector_id(metadata['brand'])
            vector_id = f"{safe_brand}_GENERAL_{i}_{int(timestamp)}"
            
            vector = {
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    **metadata,
                    "text": chunk,
                    "chunk_index": i,
                    "content_type": "GENERAL"
                }
            }
            vectors_to_upsert.append(vector)
            
        except Exception as e:
            continue
    
    print(f"      ✅ General content: {len(general_chunks)} chunks")
    
    if vectors_to_upsert:
        batch_size = 100
        for i in range(0, len(vectors_to_upsert), batch_size):
            batch = vectors_to_upsert[i:i+batch_size]
            index.upsert(vectors=batch, namespace="company_knowledge")
        
        product_count = sum(1 for v in vectors_to_upsert if v['metadata'].get('content_type') == 'PRODUCT')
        print(f"   📤 Uploaded {len(vectors_to_upsert)} vectors ({product_count} PRODUCT, {len(vectors_to_upsert)-product_count} GENERAL)")
    else:
        print(f"   ⚠️ No vectors to upload")

WEBSITES = [
    {"url": "https://avtd.com/", "name": "Торговий Дім АВ Main", "brand": "Торговий Дім АВ", "type": "distributor"},
    {"url": "https://www.dovbush.com.ua/", "name": "DOVBUSH", "brand": "DOVBUSH", "type": "cognac"},
    {"url": "https://greendayvodka.com/uk/", "name": "Green Day", "brand": "GREENDAY", "type": "vodka"},
    {"url": "https://villaua.com/", "name": "Villa", "brand": "VILLA", "type": "wine"},
    {"url": "https://helsinki.ua/", "name": "Helsinki", "brand": "HELSINKI", "type": "vodka"},
    {"url": "https://ukrainka.ua/", "name": "UKRAINKA", "brand": "UKRAINKA", "type": "vodka"},
    {"url": "https://wineviaggio.com/", "name": "Wineviaggio", "brand": "WINEVIAGGIO", "type": "wine"},
]

def enrich_content_with_rebrand(content: str, brand: str) -> str:
    """
    Normalize company name variations to Торговий Дім АВ.
    Websites may use old names, but Maya should use the new brand name!
    """
    
    replacements = {
        "Best Brands": "Торговий Дім АВ",
        "BestBrands": "Торговий Дім АВ",
        "AVTD": "Торговий Дім АВ",
        "АВТД": "Торговий Дім АВ",
        "АВ ТД": "Торговий Дім АВ",
        "ТД «АВ»": "Торговий Дім АВ",
        "TD AV": "Торговий Дім АВ",
        "АВ Group": "Торговий Дім АВ",
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

[COMPANY CONTEXT: {brand} is distributed by Торговий Дім АВ (Trading House AV), Ukraine's largest alcohol distributor with 40,000+ retail points. Торговий Дім АВ represents premium brands across vodka, cognac, and wine categories.]
"""
    
    return enriched + enrichment

async def scrape_single_website(website_info):
    """Scrape and enrich a single website with special product data handling"""
    print(f"\n🔍 Scraping {website_info['name']} ({website_info['url']})...")
    
    try:
        result = await scrape_full_website(
            url=website_info['url'],
            brand_name=website_info['brand']
        )
        
        content = None
        product_sections = []
        
        if result and isinstance(result, dict):
            content = result.get('all_text', '')
            
            sections = result.get('sections', {})
            for section_name, section_data in sections.items():
                product_keywords = ['продукція', 'асортимент', 'наші вина', 'products', 
                                   'collection', 'wines', 'portfolio']
                
                if any(keyword in section_name.lower() for keyword in product_keywords):
                    if section_data.get('text'):
                        product_sections.append({
                            'name': section_name,
                            'text': section_data['text'],
                            'url': section_data.get('url', '')
                        })
                        print(f"   🎯 Found PRODUCT section: {section_name} ({len(section_data['text'])} chars)")
        
        if not content or len(content) < 100:
            print(f"⚠️ Insufficient content from {website_info['name']}")
            return None
        
        enriched_content = enrich_content_with_rebrand(content, website_info['brand'])
        
        print(f"✅ Scraped {website_info['name']}: {len(content)} chars")
        print(f"   📝 Enriched with ТДАВ context")
        print(f"   🎯 Product sections found: {len(product_sections)}")
        
        return {
            "content": enriched_content,
            "product_sections": product_sections,
            "metadata": {
                "source": website_info['url'],
                "source_type": "company_website",
                "brand": website_info['brand'],
                "category": website_info['type'],
                "company": "Торговий Дім АВ",
                "enriched": True,
                "has_products": len(product_sections) > 0,
                "product_section_count": len(product_sections),
                "scraped_at": datetime.now().isoformat()
            }
        }
            
    except Exception as e:
        print(f"❌ Error scraping {website_info['name']}: {e}")
        import traceback
        traceback.print_exc()
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
    """Ingest all data with product section handling"""
    print("\n📤 Ingesting to RAG...")
    
    success_count = 0
    total_product_sections = 0
    
    for item in scraped_data:
        try:
            print(f"\n🔄 Processing {item['metadata']['brand']}...")
            
            ingest_scraped_content_to_pinecone(
                content=item["content"],
                product_sections=item.get("product_sections", []),
                metadata=item["metadata"]
            )
            
            if item.get("product_sections"):
                total_product_sections += len(item["product_sections"])
            
            print(f"✅ Ingested {item['metadata']['brand']}")
            success_count += 1
            
        except Exception as e:
            print(f"❌ Error ingesting {item['metadata']['brand']}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n📊 Successfully ingested {success_count}/{len(scraped_data)} brands")
    print(f"🎯 Total PRODUCT sections ingested: {total_product_sections}")

async def main():
    """Main batch processing"""
    print("=" * 60)
    print("🏭 BATCH WEBSITE INGESTION - ТДАВ REBRAND")
    print("=" * 60)
    
    scraped_data = await batch_scrape_websites()
    
    if not scraped_data:
        print("❌ No data scraped")
        return
    
    ingest_to_rag(scraped_data)
    
    print("\n" + "=" * 60)
    print("✅ BATCH INGESTION COMPLETE!")
    print(f"📊 Processed {len(scraped_data)}/{len(WEBSITES)} websites")
    print("🔄 All legacy mentions replaced with Торговий Дім АВ")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
