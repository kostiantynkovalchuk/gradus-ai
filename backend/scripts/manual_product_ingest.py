"""
Manual product ingestion for GREENDAY - COMPLETE PRODUCT LINE
All 10 products with technology details
"""

import os
import sys
sys.path.insert(0, '/home/runner/workspace/backend')

from datetime import datetime
from services.rag_utils import chunk_text, get_embedding
from pinecone import Pinecone

PRODUCTS = {
    "GREENDAY": """
GREENDAY VODKA - COMPLETE PRODUCT LINE (10 Products)

=== CORE LINE (6 Products) ===

GREENDAY CLASSIC
Perfectly pure classic vodka with a special smooth taste. The inclusion of oat flakes in the recipe rounds out the flavour of the drink, making it harmonious and balanced. Turn on the green light to your freedom!
Capacity: 0.2L, 0.375L, 0.5L, 0.7L, 1L
Alcohol: 40%

GREENDAY AIR
Vodka with an incredibly delicate and light taste that will pleasantly surprise you. During the filtration process, water is purified and enriched with oxygen, providing the airy lightness of GREENDAY AIR. Enjoy the lightness of natural vodka, and let the morning be good!
Capacity: 0.5L, 0.7L
Alcohol: 40%

GREENDAY ORIGINAL LIFE
Original vodka. Uncompromising quality. It distinguishes itself with a clean and smooth taste without any extraneous undertones. It undergoes an additional cycle of sequential triple filtration through carbon, silver, and platinum filters.
Capacity: 0.2L, 0.375L, 0.5L, 0.7L, 1L
Alcohol: 40%

GREENDAY ULTRA SOFT
Vodka with the softest taste in the GREENDAY range. The unique soft taste is based on water softening technology through ion exchange resins. Using the Silk Stream technology, we obtain additionally softened and pure water, which creates a truly silky softness of GREENDAY ULTRA SOFT.
Capacity: 0.5L, 0.7L
Alcohol: 40%

GREENDAY CRYSTAL
Additional deep polishing filtration filters ensure GREENDAY CRYSTAL's crystal-clear taste and the silkiness of premium vodkas.
Capacity: 0.1L, 0.5L, 0.7L, 1L
Alcohol: 40%

GREENDAY СМАКОBI (Flavored Line)
GreenDay Lemon – новий погляд на цитрусовий смак у горілці. Як завжди, смачний та ненабридливий, приємно п'ється. Делікатний присмак лимону у смаку та ароматі. Можна споживати як у чистому вигляді, так і у коктейлях.

GreenDay Hot Spices - у основі напою насті вічної перцевої класики – зеленого перцю халапеньйо. Наразі це краща перцева горілка в Україні. Такою її робить чудова, в міру гостра рецептура – зігріває та підвищує настрій.

GreenDay Green Tea - найкращий зелений чай роблять у Китаї, а найкращу горілку на зеленому китайському чаї зробив GreenDay. Смак майже непомітний, але він добре робить свою справу, горілка п'ється як класична біла, а тому п'ється легко.
Capacity: 0.5L
Alcohol: 40%

=== EVOLUTION LINE (4 Products) ===

GREENDAY EVOLUTION
GREENDAY EVOLUTION vodka is a vodka that meets high international standards in the vodka industry and boldly challenges global brands. This product stands out from others with its ultra-modern design. GREENDAY EVOLUTION sets itself apart with its ultra-modern design and represents the pinnacle of the company's evolution, during which the brand's team created a flawless product.
Capacity: 0.5L, 0.75L
Alcohol: 40%

GREENDAY PLANET
Робляchi крок вперед, живучи в ногу з усіма світовими інноваціями – ти живеш, оточуючи себе тільки обраним, справжнім, природним. Якщо ти віддаєш перевагу справжньому, природному та найкращому, обирай GREENDAY PLANET
Capacity: 0.5L, 0.75L
Alcohol: 40%

GREENDAY DISCOVERY
GREENDAY DISCOVERY is a world-class elite vodka for those who are open to change and derive pleasure from everything happening in their lives. GREENDAY DISCOVERY is made specifically for them. The name DISCOVERY was chosen deliberately. It truly embodies the discovery of purity of taste and delicate smoothness.
Capacity: 0.5L, 0.75L
Alcohol: 40%

GREENDAY ORGANIC
Premium organic vodka in the Evolution line. Made with organic ingredients and eco-conscious production methods, representing GREENDAY's commitment to natural quality and environmental responsibility.
Capacity: 0.5L, 0.75L
Alcohol: 40%

=== TECHNOLOGY ===

CRYSTAL POINT Deep Filtration
Даний опис застосовується і до осмотичної фільтрації води та до фільтрації на установках перед розливом. Зворотний осмос – для очищення води на молекулярному рівні від різних домішок, мікробів та бактерій. Очищення здійснюється за допомогою напівпроникних синтетичних мембран.

TRIPLE FINE FILTRATION
Фільтрація водно-спиртової суміші на установках, в яких встановлені патронні фільтруючі елементи марки ЕПСФ.УРt (Платинова фільтрація) та ЕПСФ.УАg (срібна фільтрація) на основі активованого вугілля зі шкаралупи кокосового горіха імпрегнованого платиною та сріблом.

SERVING SUGGESTION - Vodka on the Rocks
"Vodka on the rocks" is a unique way and style of consuming vodka. In a special crystal glass called a "rocks" glass, typically used for serving whiskey or rum, add lime cubes and GreenDay vodka. This presentation gives the drink a special taste and a new status - change your own habits with GreenDay vodka.
"""
}

def manual_ingest():
    """Manually ingest complete GREENDAY product data"""
    
    PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
    
    if not PINECONE_API_KEY or not PINECONE_INDEX_NAME:
        print("❌ Environment variables not set!")
        return
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    total_uploaded = 0
    
    for brand, content in PRODUCTS.items():
        
        print(f"\n{'='*60}")
        print(f"🔄 Processing {brand} - COMPLETE PRODUCT LINE")
        print(f"{'='*60}")
        
        enriched = f"""{content}

[COMPANY CONTEXT: {brand} is distributed by Best Brands, Ukraine's largest alcohol distributor with 40,000+ retail points. Best Brands (formerly AVTD) represents premium brands across vodka, cognac, and wine categories.]
"""
        
        chunks = chunk_text(enriched, chunk_size=500, overlap=50)
        print(f"   📦 Created {len(chunks)} chunks")
        print(f"   🎯 Covering 10 products + technology details")
        
        vectors = []
        
        for i, chunk in enumerate(chunks):
            try:
                embedding = get_embedding(chunk)
                
                timestamp = int(datetime.now().timestamp())
                vector_id = f"{brand}_PRODUCT_MANUAL_{i}_{timestamp}"
                
                vector = {
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "text": chunk,
                        "brand": brand,
                        "source": "https://greendayvodka.com/uk/",
                        "source_type": "company_website",
                        "category": "vodka",
                        "company": "Best Brands",
                        "content_type": "PRODUCT",
                        "is_product_info": True,
                        "section_name": "Complete Product Line",
                        "enriched": True,
                        "chunk_index": i,
                        "scraped_at": datetime.now().isoformat()
                    }
                }
                vectors.append(vector)
                
            except Exception as e:
                print(f"   ⚠️ Error on chunk {i}: {e}")
                continue
        
        if vectors:
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i+batch_size]
                index.upsert(vectors=batch, namespace="company_knowledge")
            
            print(f"   📤 Uploaded {len(vectors)} vectors")
            print(f"   🎯 All tagged with content_type='PRODUCT'")
            print(f"   ✅ Maya now knows ALL 10 GREENDAY products!")
            total_uploaded += len(vectors)
        
        print(f"✅ Ingested {brand}")
    
    print(f"\n{'='*60}")
    print(f"✅ MANUAL INGESTION COMPLETE!")
    print(f"📊 Total vectors uploaded: {total_uploaded}")
    print(f"🎯 All tagged as PRODUCT for priority retrieval!")
    print(f"🍸 Coverage: 10 products + filtration technology + serving")
    print(f"{'='*60}")

if __name__ == "__main__":
    manual_ingest()
