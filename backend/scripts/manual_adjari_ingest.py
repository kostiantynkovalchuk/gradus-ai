"""
Manual product ingestion for ADJARI - COMPLETE PRODUCT LINE
Cognacs and Wines from official website
"""

import os
import sys
sys.path.insert(0, '/home/runner/workspace/backend')

from datetime import datetime
from services.rag_utils import chunk_text, get_embedding
from pinecone import Pinecone

PRODUCTS = {
    "ADJARI": """
ADJARI - COMPLETE PRODUCT LINE (Georgian Cognacs & Wines)

=== COGNAC LINE (6 Products) ===

ADJARI 3*
Класичний коньяк 3-річної витримки з м'яким ванільно-карамельним відтінком, фруктовими та шоколадними нотками і ароматом інжиру.
Volumes: 1L, 0.5L, 0.25L, 0.1L
Alcohol: Standard cognac strength

ADJARI 4* КВАРТЕЛИ
Класичний коньяк 4-річної витримки має оригінальний та неповторний смак. Відкривається персиковим ароматом в ансамблі з шоколадно-ванільними нотами та завершується витонченим горіховим післясмаком. Колір насичений янтарний. Смак надзвичайно м'який та округлий.
Volumes: 0.5L, 0.25L
Alcohol: Standard cognac strength

ADJARI 5*
Класичний коньяк 5-річної витримки з більш насиченим і багатогранним букетом. У карамельних нотах відчувається м'якість, що поєднується з бархатистою горіховою терпкістю і легкими фруктовими тонами. Завершується ансамбль приємним шоколадним смаком.
Volumes: 1L, 0.5L, 0.25L, 0.1L
Alcohol: Standard cognac strength

ADJARI 5* в тубусі
Premium gift packaging version of 5-star cognac
Volumes: 0.5L
Alcohol: Standard cognac strength

ADJARI 7* МУДРИЙ АДЖАРЕЛІЯ
Класичний марочний коньяк 7-річної витримки має чудовий аромат, інтенсивний смак та тривалий післясмак. У цитрусових та ванільних нотах відчувається м'який та вишуканий аромат. Продовжується ансамбль витонченими горіховими та фруктовими тонами в смаку, а довершує ансамбль приємний шоколадний смак.
Volumes: 0.5L
Alcohol: Standard cognac strength

=== COGNAC PRODUCTION ===

Виноматеріал: Зі стиглих, налитих сонцем ягід винограду
Витримка: Надає коньяку особливий колір, аромат і післясмак (3% випаровування щороку - "частка янголів")
Аромат: Виразні ванільно-шоколадні ноти, характерні для благородного коньяку
Смак: Дуже округлий і збалансований без сторонніх спиртових відтінків

Traditional Georgian production methods with oak barrel aging. After 7-8% alcohol fermentation, double distillation produces 70% spirit, which then ages in oak barrels for 3-7+ years.

=== WINE LINE (6 Varieties) ===

ACHURULI (Ачарулі)
Вино столове напівсолодке біле
Grape varieties: Ркацителі, Аліготе
Flavor: Повний, гармонійний, з пікантною гірчинкою в післясмаку
Aroma: Квітково-пряний з нотами меду
Volume: 0.75L
Alcohol: 9.0-13.0% vol
Sugar: 3.0-8.0% mass
Pairing: Хачапурі, піца, страви з хлібом та сиром

ALAZANI VALLEY БІЛЕ (Алазанська долина)
Вино столове напівсолодке біле
Grape varieties: Ркацителі та європейські білі сорти
Aroma: Мигдалю з легким димним відтінком, нотами медової дині, яблука і цітрусових
Flavor: Легкий освіжаючий з нотами тропічних фруктів
Volume: 0.75L
Alcohol: 9.0-13.0% vol
Sugar: 3.0-8.0% mass
Pairing: М'ясо птиці, сири, легкі салати з вершковою заправкою

SAPERAVI (Сапераві)
Вино столове сухе червоне
Grape varieties: 100% Сапераві
Color: Глибокий темно-гранатовий
Flavor: Насичений інтенсивний смак з легкою терпкістю чорниці та шовковиці
Aroma: Легкі тони малини, фіалок і чорноплідної горобини
Volume: 0.75L
Alcohol: 9.5-14.0% vol
Dry wine

PIROSMANI (Пиросмані)
Вино столове напівсухе червоне
Grape varieties: Сапераві і Мерло
Aroma: Ожини, черешні, малини, фіалки і дикої сливи
Flavor: М'який, округлий, легкий з тонким присмаком ягід і ледь вловимими нотами какао
Volume: 0.75L
Alcohol: 9.0-14.0% vol
Sugar: 0.5-2.5% mass
Pairing: Ніжні паштети та м'ясні салати

ALAZANI VALLEY ЧЕРВОНЕ (Алазанська долина)
Вино столове напівсолодке червоне
Grape varieties: Сапераві і Бастардо Магарачский
Aroma: Чорна смородина, ноти граната, вишневі мотиви, ожина і чорнослив
Flavor: Виразний, приємно солодкуватий з ніжною кислинкою
Volume: 0.75L
Alcohol: 9.0-13.0% vol
Sugar: 3.0-8.0% mass
Pairing: Прекрасний аперитив, солодкі десерти

DOLURI (Долурі)
Вино столове напівсолодке червоне
Grape varieties: Сапераві і Каберне-Совіньйон
Aroma: Чорна смородина, ожина, чорного перцю, фіалки
Flavor: Округлий, насичений фруктово-ягідний
Volume: 0.75L
Alcohol: 9.0-13.0% vol
Sugar: 3.0-8.0% mass
Pairing: Жирне м'ясо і копченості

=== WINE PRODUCTION PHILOSOPHY ===

ADJARI wines use predominantly Georgian grape varieties - Saperavi and Rkatsiteli - blended harmoniously with European varieties (Aligote, Cabernet Sauvignon, Bastardo, Merlot). Traditional Georgian winemaking involves fermentation with grape juice, skins, seeds, pulp, and even stems, creating intensely colored, richly aromatic, and unforgettably flavorful wines.

The wines are bright, saturated, and unmistakably memorable - like the rhythms of the national Georgian dance Acharuli and the melodies of mountain songs Doluri.

=== BRAND HERITAGE ===

Adjara is a paradise corner at the foot of the Caucasus mountains, bathed in greenery year-round and washed by the Black Sea. The ancient land is known for exceptional mild climate, majestic nature, and the juiciest grapes. Adjara is famous for its hospitality - reflected in every bottle of ADJARI cognac and wine.
"""
}

def manual_ingest():
    """Manually ingest complete ADJARI product data"""
    
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
        print(f"   🎯 Covering 6 cognacs + 6 wines + production details")
        
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
                        "source": "https://adjari.com.ua/",
                        "source_type": "company_website",
                        "category": "cognac_wine",
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
            print(f"   ✅ Maya now knows ALL ADJARI products!")
            print(f"   🥃 6 Cognacs: 3*, 4* Квартели, 5*, 5* тубус, 7* Мудрий")
            print(f"   🍷 6 Wines: Ачарулі, Алазанська (2), Сапераві, Пиросмані, Долурі")
            total_uploaded += len(vectors)
        
        print(f"✅ Ingested {brand}")
    
    print(f"\n{'='*60}")
    print(f"✅ MANUAL INGESTION COMPLETE!")
    print(f"📊 Total vectors uploaded: {total_uploaded}")
    print(f"🎯 All tagged as PRODUCT for priority retrieval!")
    print(f"🥃🍷 Coverage: 6 cognacs + 6 wines + production heritage")
    print(f"{'='*60}")

if __name__ == "__main__":
    manual_ingest()
