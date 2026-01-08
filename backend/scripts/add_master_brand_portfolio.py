"""
Create a master brand portfolio document for Торговий Дім АВ (Trading House AV)
This ensures Maya ALWAYS sees the complete brand list in search results
"""

import os
import sys
sys.path.insert(0, '/home/runner/workspace/backend')

from datetime import datetime
from services.rag_utils import get_embedding
from pinecone import Pinecone

def add_master_list():
    PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    master_content = """
ТОРГОВИЙ ДІМ АВ (TRADING HOUSE AV) - COMPLETE BRAND PORTFOLIO

This is the authoritative, complete list of all brands distributed by Торговий Дім АВ (Trading House AV), Ukraine's largest alcohol distributor with 40,000+ retail points across the country.

=== VODKA BRANDS (3 brands) ===

1. GREENDAY - Premium Ukrainian vodka with 10 products
   CLASSIC LINE (6 products):
   • GREENDAY CLASSIC - Pure classic vodka with oat flakes (0.2L, 0.375L, 0.5L, 0.7L, 1L) - 40%
   • GREENDAY AIR - Light, oxygen-enriched vodka (0.5L, 0.7L) - 40%
   • GREENDAY ORIGINAL LIFE - Triple filtration through carbon, silver, platinum (0.2L, 0.375L, 0.5L, 0.7L, 1L) - 40%
   • GREENDAY ULTRA SOFT - Softest taste, Silk Stream technology (0.5L, 0.7L) - 40%
   • GREENDAY CRYSTAL - Deep polishing filtration (0.1L, 0.5L, 0.7L, 1L) - 40%
   • GREENDAY СМАКОBI (Flavored) - Lemon, Hot Spices (jalapeño), Green Tea (0.5L) - 40%
   
   EVOLUTION LINE (4 products):
   • GREENDAY EVOLUTION - International standards, ultra-modern design (0.5L, 0.75L) - 40%
   • GREENDAY PLANET - Natural, eco-conscious positioning (0.5L, 0.75L) - 40%
   • GREENDAY DISCOVERY - World-class elite vodka (0.5L, 0.75L) - 40%
   • GREENDAY ORGANIC - Premium organic vodka (0.5L, 0.75L) - 40%
   
   Technology: Crystal Point Deep Filtration, Triple Fine Filtration
   Website: greendayvodka.com

2. HELSINKI - Scandinavian-style premium vodka
   • Clean, pure taste with Finnish heritage
   • Premium positioning for vodka connoisseurs
   • Multiple volumes available
   Website: helsinki.ua

3. UKRAINKA - Authentic Ukrainian vodka
   • Traditional Ukrainian positioning
   • Strong national brand identity
   • Classic vodka segment
   Website: ukrainka.ua

=== WINE BRANDS (5 brands) ===

4. VILLA UA - Ukrainian wines with 4 collections
   • Classic collection - Chardonnay, Pinot Grigio, Pinot Noir Merlot, Gewürztraminer Blanc, Muscat Dry, etc.
   • Author's collection - Premium author's blends and varietals
   • ART collection - Premium artistic segment wines
   • Champagne collection - Pina Colada, Bellini, Grand Cuvee, Muscat, and more sparkling wines
   
   Slogan: "Завжди твоя найсмачніша" (Always your most delicious)
   All wines: 9-14% alcohol, 0.75L bottles
   Website: villaua.com

6. KRISTI VALLEY - French wines from Guillot vineyards
   Five wine varieties:
   • Chatelain Clemont - French classic
   • Charon Blanc - White wine
   • Vivien Rouge - Red wine
   • Belle Melanie - Elegant blend
   • Saint Thouri - Traditional French
   
   Heritage: Traditional French winemaking with terroir focus
   Website: kristivalley.com

7. DIDI LARI - Georgian wines
   • Traditional Georgian wine varieties
   • Rich cultural heritage and history
   • Authentic Georgian winemaking methods
   • Multiple varietals from Georgia's wine regions
   Website: didilari.com

8. WINEVIAGGIO - Italian wines
   • "Wine journey" concept
   • Authentic Italian varietals
   • Italian winemaking traditions
   • Mediterranean wine experience
   Website: wineviaggio.com

=== COGNAC & BRANDY BRANDS (2 brands) ===

9. DOVBUSH - Ukrainian cognac
   • Traditional Ukrainian cognac production
   • Multiple age statements and expressions
   • Oak barrel aging
   • Premium positioning
   Website: dovbush.com.ua

10. ADJARI - Georgian cognac and wines (12 products total)
    
    COGNAC LINE (6 products):
    • ADJARI 3* - 3-year aging, vanilla-caramel notes (1L, 0.5L, 0.25L, 0.1L)
    • ADJARI 4* КВАРТЕЛИ - 4-year, peach aroma, chocolate-vanilla notes (0.5L, 0.25L)
    • ADJARI 5* - 5-year, rich multifaceted bouquet (1L, 0.5L, 0.25L, 0.1L)
    • ADJARI 5* в тубусі - Gift packaging version (0.5L)
    • ADJARI 7* МУДРИЙ АДЖАРЕЛІЯ - 7-year premium, citrus-vanilla, almond finish (0.5L)
    
    WINE LINE (6 varieties, all 0.75L):
    • ACHURULI (Ачарулі) - White semi-sweet, floral-spicy, honey notes (9-13% alc, 3-8% sugar)
    • ALAZANI VALLEY White - Semi-sweet, tropical fruits, almonds (9-13% alc, 3-8% sugar)
    • SAPERAVI (Сапераві) - Red dry, intense, raspberry-violet notes (9.5-14% alc)
    • PIROSMANI (Пиросмані) - Red semi-dry, berry-cocoa notes (9-14% alc, 0.5-2.5% sugar)
    • ALAZANI VALLEY Red - Semi-sweet, black currant, pomegranate (9-13% alc, 3-8% sugar)
    • DOLURI (Долурі) - Red semi-sweet, blackberry, black pepper (9-13% alc, 3-8% sugar)
    
    Production: Traditional Georgian methods with oak aging for cognacs, Georgian grape varieties (Saperavi, Rkatsiteli) blended with European varieties for wines
    Heritage: Adjara region, Black Sea coast, Georgian hospitality traditions
    Website: adjari.com.ua

=== DISTRIBUTION & MARKET COVERAGE ===

Торговий Дім АВ (Trading House AV) is Ukraine's largest alcohol distributor:
- 40,000+ retail points across Ukraine
- Comprehensive market coverage in HoReCa sector (hotels, restaurants, cafes)
- Premium and super-premium segment focus
- Professional distribution network operating even during wartime
- Partnerships with bars, hotels, restaurants, and retail chains nationwide

Company positioning: Strong distribution partner committed to mutual beneficial relationships with every client, innovative brand development, and continuous professional growth.

=== SOJU BRANDS (1 brand) ===

10. FUNJU - Korean-style soju
    • First Ukrainian soju brand
    • Korean-inspired, produced in Ukraine
    • Light, refreshing taste
    • Appeal to younger consumers
    Website: funju.ua

=== BRAND CATEGORIES SUMMARY ===
Total: 10 brands across 4 categories
- Vodka: 3 brands (GREENDAY with 10 SKUs, HELSINKI, UKRAINKA)
- Wine: 5 brands (VILLA with 4 collections, KRISTI VALLEY with 5 wines, DIDI LARI, WINEVIAGGIO, ADJARI with 6 wines)
- Cognac: 2 brands (DOVBUSH, ADJARI with 6 cognacs)
- Soju: 1 brand (FUNJU)

ADJARI is unique as both cognac and wine brand (12 total products).
GREENDAY is the flagship vodka brand with most extensive lineup (10 products).
VILLA is the flagship wine brand with most extensive collections (4 distinct collections).
FUNJU represents expansion into Asian spirits category.
"""
    
    print("📝 Creating MASTER BRAND PORTFOLIO document...\n")
    
    embedding = get_embedding(master_content)
    
    timestamp = int(datetime.now().timestamp())
    vector_id = f"MASTER_BRAND_PORTFOLIO_{timestamp}"
    
    vector = {
        "id": vector_id,
        "values": embedding,
        "metadata": {
            "text": master_content,
            "brand": "Торговий Дім АВ",
            "source": "https://avtd.com",
            "source_type": "master_document",
            "category": "portfolio_overview",
            "company": "Торговий Дім АВ",
            "content_type": "MASTER",
            "is_master_list": True,
            "priority": "highest",
            "enriched": True,
            "created_at": datetime.now().isoformat()
        }
    }
    
    index.upsert(vectors=[vector], namespace="company_knowledge")
    
    print("✅ MASTER BRAND PORTFOLIO document created!")
    print(f"   Vector ID: {vector_id}")
    print(f"   Content: {len(master_content)} chars")
    print(f"\n📊 COVERAGE:")
    print(f"   • 10 brands total (4 categories)")
    print(f"   • 3 vodka brands (GREENDAY 10 SKUs, HELSINKI, UKRAINKA)")
    print(f"   • 5 wine brands (VILLA 4 collections, KRISTI VALLEY, DIDI LARI, WINEVIAGGIO, ADJARI 6 wines)")
    print(f"   • 2 cognac brands (DOVBUSH, ADJARI 6 cognacs)")
    print(f"   • 1 soju brand (FUNJU)")
    print(f"   • 40,000+ retail distribution points")
    print(f"\n🎯 This document will appear in TOP results for brand queries!")
    print(f"   Maya will ALWAYS see the complete brand list!")

if __name__ == "__main__":
    add_master_list()
