"""
Premium Unsplash Image Fetching Service
4-Tier intelligent search strategy for GradusMedia

Tiers:
0. Geographical (if country mentioned)
1. Context-based (business/production/etc)
2. HoReCa/Cocktail fallback
3. Safe abstract premium
"""
import os
import requests
import logging
import random
import re
from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session
from models import get_db

logger = logging.getLogger(__name__)

UNSPLASH_API_URL = "https://api.unsplash.com"
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

# ============================================================
# TIER 0: GEOGRAPHICAL IMAGERY - International Content
# ============================================================

GEOGRAPHICAL_KEYWORDS = {
    # Western Europe
    "netherlands|dutch|holland|amsterdam|нідерланд|голланд|амстердам": [
        "amsterdam canal houses golden hour architecture",
        "dutch windmill countryside aerial view",
        "tulip fields netherlands colorful landscape",
        "rotterdam modern architecture waterfront"
    ],
    
    "france|french|bordeaux|champagne|cognac|burgundy|франц|бордо|шампань|коньяк|бургунд": [
        "bordeaux vineyard rows aerial sunset",
        "french countryside provence landscape golden",
        "burgundy wine region rolling hills",
        "champagne region vineyards france aerial",
        "cognac region vineyard landscape"
    ],
    
    "italy|italian|tuscany|piedmont|італ|тоскан|п'ємонт": [
        "tuscany vineyard sunset rolling hills",
        "italian countryside villa landscape aerial",
        "piedmont wine region italy dramatic",
        "sicilian vineyard mount etna landscape"
    ],
    
    "spain|spanish|rioja|catalonia|іспан|ріоха|каталон": [
        "spanish vineyard landscape golden hour",
        "rioja wine region aerial view sunset",
        "catalonia vineyard rows dramatic",
        "andalusia countryside landscape golden"
    ],
    
    "portugal|portuguese|porto|douro|португал|порту|дору": [
        "douro valley vineyard terraces aerial",
        "portuguese vineyard landscape dramatic",
        "porto wine region aerial sunset",
        "portugal countryside golden hour"
    ],
    
    "germany|german|rhine|mosel|німеч|рейн|мозель": [
        "rhine valley vineyard terraces dramatic",
        "german countryside landscape rolling hills",
        "mosel river vineyard aerial view",
        "germany wine region landscape"
    ],
    
    "scotland|scottish|speyside|islay|highlands|шотланд|спейсайд|айла": [
        "scottish highlands dramatic landscape moody",
        "isle of islay coastal scenery atmospheric",
        "speyside region scotland aerial view",
        "scotland loch mountains dramatic lighting"
    ],
    
    "ireland|irish|dublin|ірланд|дублін": [
        "irish countryside green rolling hills",
        "ireland coastal cliffs dramatic sunset",
        "dublin whiskey district architecture",
        "emerald isle landscape aerial dramatic"
    ],
    
    "england|english|britain|uk|англ|британ": [
        "english countryside rolling hills pastoral",
        "british landscape green hills dramatic",
        "cotswolds landscape golden hour",
        "uk countryside scenic aerial"
    ],
    
    # Americas
    "usa|america|united states|сша|америк": [
        "napa valley vineyard aerial sunset",
        "california wine country landscape golden",
        "american countryside rolling hills",
        "sonoma valley golden hour vineyard"
    ],
    
    "kentucky|bourbon|кентуккі|бурбон": [
        "kentucky bourbon country landscape pastoral",
        "kentucky countryside rolling hills golden",
        "american south landscape pastoral scenic",
        "bourbon country kentucky aerial view"
    ],
    
    "mexico|mexican|jalisco|oaxaca|tequila|мексик|халіско|оахака|текіла": [
        "jalisco agave field blue landscape dramatic",
        "tequila region mexico aerial view",
        "oaxaca countryside landscape golden hour",
        "mexican highlands dramatic scenery sunset"
    ],
    
    "canada|canadian|ontario|quebec|канад|онтаріо|квебек": [
        "canadian vineyard okanagan valley sunset",
        "niagara region vineyard aerial view",
        "quebec countryside scenic landscape",
        "ontario wine country golden hour"
    ],
    
    "chile|chilean|чилі": [
        "chilean vineyard andes mountains backdrop",
        "colchagua valley landscape aerial sunset",
        "chile wine region dramatic scenery",
        "south american vineyard andes sunset"
    ],
    
    "argentina|argentinian|mendoza|аргентин|мендоса": [
        "mendoza vineyard andes backdrop sunset",
        "argentinian wine region landscape dramatic",
        "patagonia landscape dramatic lighting",
        "mendoza wine country aerial view"
    ],
    
    "brazil|brazilian|бразил": [
        "brazilian countryside landscape golden",
        "south american vineyard scenic aerial",
        "brazil wine region landscape sunset",
        "latin american countryside dramatic"
    ],
    
    # Asia-Pacific
    "japan|japanese|tokyo|kyoto|японі|японськ|токіо|кіото": [
        "japanese sake brewery traditional architecture",
        "kyoto traditional architecture atmospheric moody",
        "japan rice terraces aerial view dramatic",
        "japanese craftsmanship aesthetic minimal elegant"
    ],
    
    "china|chinese|китай|китайськ": [
        "chinese rice terraces yuanyang aerial dramatic",
        "traditional chinese architecture atmospheric",
        "asian countryside landscape dramatic sunset",
        "china wine region landscape aerial"
    ],
    
    "india|indian|інді": [
        "indian countryside landscape golden hour",
        "asian agricultural landscape aerial",
        "indian terraces landscape dramatic",
        "south asian countryside scenic"
    ],
    
    "australia|australian|австралі": [
        "australian vineyard landscape aerial sunset",
        "barossa valley vineyard golden hour",
        "margaret river landscape scenic dramatic",
        "australian wine country rolling hills"
    ],
    
    "new zealand|нова зеланд": [
        "new zealand vineyard landscape dramatic mountains",
        "marlborough region aerial view sunset",
        "central otago vineyard mountains backdrop",
        "new zealand countryside scenic dramatic"
    ],
    
    # Eastern Europe
    "georgia|georgian|грузі": [
        "georgian vineyard kakheti region landscape",
        "caucasus mountains vineyard dramatic sunset",
        "traditional georgian winery landscape",
        "eastern european countryside golden"
    ],
    
    "ukraine|ukrainian|україн": [
        "ukrainian countryside landscape golden sunset",
        "eastern european pastoral landscape",
        "ukrainian wheat field aerial view",
        "ukraine rural landscape dramatic"
    ],
    
    "poland|polish|польщ|польськ": [
        "polish countryside landscape golden",
        "eastern european rural landscape",
        "poland agricultural landscape aerial",
        "polish pastoral landscape sunset"
    ],
    
    # Africa
    "south africa|african|південь африк|африканськ": [
        "south african vineyard stellenbosch sunset",
        "cape winelands landscape aerial dramatic",
        "african vineyard sunset golden hour",
        "south africa countryside scenic mountains"
    ]
}

# ============================================================
# TIER 1: CONTEXT-BASED KEYWORDS
# ============================================================

CONTEXT_KEYWORDS = {
    "business_legal": {
        "triggers": ["закон", "регул", "політик", "кодекс", "правил", "суд", "позов", "право", "захист", 
                     "law", "regulation", "policy", "code", "legal", "lawsuit", "court", "protection",
                     "угода", "контракт", "ліцензі"],
        "searches": [
            "corporate boardroom modern minimal architecture",
            "business handshake professional elegant dark",
            "executive meeting glass building modern",
            "contract signing professional elegant",
            "law office elegant dark wood sophisticated",
            "business people discussion modern minimal",
            "corporate office interior premium dark"
        ]
    },
    
    "market_industry": {
        "triggers": ["ринок", "індустрія", "експорт", "продаж", "зростання", "торгів", "market", 
                     "industry", "export", "sales", "growth", "trade", "shipping", "імпорт", "обсяг"],
        "searches": [
            "global business network abstract concept",
            "shipping containers port aerial view",
            "warehouse logistics modern industrial",
            "business growth abstract minimal dark",
            "international trade concept elegant",
            "distribution center premium modern",
            "cargo ship aerial view dramatic"
        ]
    },
    
    "production": {
        "triggers": ["виробниц", "завод", "дистилер", "броварн", "винороб", "production", 
                     "distillery", "brewery", "winery", "manufacturing", "plant", "фабрик"],
        "searches": [
            "copper distillery equipment vintage atmospheric",
            "oak barrel aging cellar dramatic lighting",
            "industrial copper still atmospheric moody",
            "craftsmanship hands working tools closeup",
            "production line modern clean industrial",
            "stainless steel equipment industrial premium"
        ]
    },
    
    "brand_product": {
        "triggers": ["бренд", "продукт", "новинк", "запуск", "презент", "інновац", "brand", 
                     "product", "launch", "innovation", "release", "new", "лінійк", "колекці"],
        "searches": [
            "luxury product photography minimal dark elegant",
            "premium packaging design sophisticated",
            "artisan craftsmanship hands elegant",
            "modern design aesthetic minimal dark",
            "innovation concept abstract elegant",
            "sophisticated product display premium"
        ]
    },
    
    "sustainability": {
        "triggers": ["екологі", "сталий", "зелен", "природ", "органіч", "ecology", 
                     "sustainable", "green", "organic", "environment", "eco", "біо"],
        "searches": [
            "sustainable materials natural light organic",
            "organic farming aerial view landscape",
            "green business concept minimal",
            "renewable resources abstract elegant",
            "nature conservation landscape dramatic",
            "eco friendly production modern"
        ]
    },
    
    "events": {
        "triggers": ["подія", "свято", "церемон", "нагород", "фестива", "event", 
                     "celebration", "ceremony", "award", "festival", "conference", "конференц"],
        "searches": [
            "elegant event venue lighting atmospheric",
            "celebration toast champagne abstract dark",
            "award ceremony elegant sophisticated",
            "gala event sophisticated premium lighting",
            "festive atmosphere premium elegant",
            "luxury party venue moody dramatic"
        ]
    },
    
    "supermarket_retail": {
        "triggers": ["супермаркет", "магазин", "рітейл", "роздріб", "полиц", "supermarket",
                     "retail", "store", "shelf", "shop", "торгов"],
        "searches": [
            "premium supermarket interior dark moody lighting",
            "grocery aisle warm atmospheric lighting elegant",
            "retail store interior modern premium",
            "liquor store shelves dramatic lighting",
            "wine shop interior elegant atmospheric",
            "premium retail space modern sophisticated"
        ]
    }
}

# ============================================================
# TIER 2: HORECA + COCKTAIL IMAGERY
# ============================================================

HORECA_KEYWORDS = [
    "luxury bar interior moody dramatic lighting",
    "cocktail bar elegant dark sophisticated atmosphere",
    "restaurant wine cellar atmospheric moody",
    "modern bar counter premium design elegant",
    "speakeasy bar vintage aesthetic moody",
    "wine cellar oak barrels dramatic lighting",
    "wine vineyard sunset golden hour aerial",
    "sommelier wine tasting professional elegant",
    "wine barrel room dramatic shadows moody",
    "vineyard rows aerial view landscape",
    "whiskey glass bokeh golden warm light",
    "oak barrel aging warehouse atmospheric",
    "copper still distillery vintage moody",
    "craft brewery equipment copper premium",
    "distillery equipment atmospheric dramatic",
    "liquid splash abstract black background",
    "golden liquid pour elegant minimal",
    "glass reflection minimal dark sophisticated",
    "bubbles carbonation macro abstract elegant",
    "amber liquid glow atmospheric moody"
]

COCKTAIL_KEYWORDS = [
    "craft cocktail dark background minimal elegant",
    "cocktail garnish artistic close up macro",
    "mixology elegant dark moody atmospheric",
    "cocktail splash abstract black background",
    "premium cocktail minimal dark sophisticated",
    "cocktail glass bokeh golden warm light",
    "crystal cocktail glass elegant dark moody",
    "cocktail ice macro photography abstract",
    "coupe glass cocktail minimal elegant dark",
    "highball glass garnish atmospheric moody",
    "bartender hands making cocktail artistic dramatic",
    "mixing cocktail shaker elegant motion blur",
    "cocktail flame dramatic lighting moody",
    "pouring cocktail elegant slow motion",
    "cocktail preparation overhead flat lay minimal",
    "cocktail bar counter moody dramatic lighting",
    "craft cocktail smoke atmospheric dark elegant",
    "cocktail ingredients flat lay minimal dark",
    "bar tools copper brass elegant vintage",
    "cocktail stirring glass macro elegant"
]

# ============================================================
# PEOPLE IMAGERY - Strategic Human Element
# ============================================================

PEOPLE_HANDS_KEYWORDS = [
    "hands holding wine glass elegant dark atmospheric",
    "sommelier hands examining wine glass backlit dramatic",
    "craftsman hands working oak barrel closeup",
    "bartender hands making cocktail artistic dramatic lighting",
    "hands toasting champagne glasses celebration elegant",
    "wine tasting hands close up atmospheric moody",
    "cooper hands crafting barrel traditional artisan",
    "winemaker hands checking grapes closeup golden",
    "bartender hands garnishing cocktail artistic elegant",
    "hands pouring wine elegant minimal dark"
]

PEOPLE_CONTEXT_KEYWORDS = [
    "sommelier from behind wine cellar dramatic lighting",
    "businesspeople walking modern building corridor",
    "bartender back view making cocktail moody",
    "vineyard worker from behind rows sunset",
    "conference attendees backs auditorium elegant",
    "chef from behind kitchen professional dramatic",
    "winemaker walking barrel room atmospheric",
    "business meeting backs conference room modern"
]

# ============================================================
# TIER 3: SAFE ABSTRACT FALLBACKS
# ============================================================

SAFE_FALLBACKS = [
    "golden hour bokeh abstract warm atmospheric",
    "dark moody atmospheric texture elegant",
    "luxury minimalist background elegant dark",
    "premium dark sophisticated ambiance moody",
    "elegant abstract lighting design minimal",
    "sophisticated dark background texture premium",
    "minimal elegant black background atmospheric",
    "warm golden light abstract bokeh",
    "dramatic lighting atmosphere premium moody",
    "refined elegant dark aesthetic minimal"
]

# ============================================================
# BRAND FILTERING
# ============================================================

BRAND_KEYWORDS = [
    "coca cola", "pepsi", "heineken", "budweiser", "corona",
    "absolut", "smirnoff", "jack daniels", "johnnie walker",
    "grey goose", "bacardi", "moet", "dom perignon",
    "guinness", "stella artois", "carlsberg", "tuborg",
    "jim beam", "makers mark", "wild turkey", "jameson",
    "baileys", "kahlua", "malibu", "jagermeister",
    "leffe", "hoegaarden", "kronenbourg",
    "logo", "brand name", "trademark", "labeled bottle",
    "brand label", "company logo"
]


class UnsplashService:
    def __init__(self):
        self.access_key = UNSPLASH_ACCESS_KEY
        self.used_image_ids: Set[str] = set()
        
    def get_used_image_ids_from_db(self) -> Set[str]:
        """Get all previously used Unsplash image IDs from database"""
        try:
            from models.content import ContentQueue
            db = next(get_db())
            used_ids = db.query(ContentQueue.unsplash_image_id).filter(
                ContentQueue.unsplash_image_id != None
            ).all()
            db.close()
            return {id[0] for id in used_ids if id[0]}
        except Exception as e:
            logger.error(f"Error fetching used image IDs: {e}")
            return set()
    
    def detect_country(self, text: str) -> Optional[str]:
        """Detect country mentioned in article and return search keyword"""
        text_lower = text.lower()
        
        for region_pattern, keywords in GEOGRAPHICAL_KEYWORDS.items():
            countries = region_pattern.split("|")
            for country in countries:
                if country in text_lower:
                    keyword = random.choice(keywords)
                    logger.info(f"🌍 TIER 0: Country detected: {country} → {keyword[:50]}...")
                    return keyword
        return None
    
    def interpret_context(self, title: str, content: str) -> Optional[str]:
        """Interpret article context and return appropriate search keyword"""
        text = f"{title} {content}".lower()
        
        for category, config in CONTEXT_KEYWORDS.items():
            triggers = config["triggers"]
            if any(trigger in text for trigger in triggers):
                keyword = random.choice(config["searches"])
                logger.info(f"🎯 TIER 1: Context detected: {category} → {keyword[:50]}...")
                return keyword
        return None
    
    def enhance_context_with_people(self, base_context: str, text: str) -> str:
        """Determine if people imagery would enhance the context"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["конференц", "зустріч", "подія", "церемон", 
                                                 "презентац", "conference", "meeting", "event"]):
            keyword = random.choice(PEOPLE_CONTEXT_KEYWORDS)
            logger.info(f"👥 People enhancement: event → {keyword[:50]}...")
            return keyword
        
        if any(word in text_lower for word in ["майстер", "виробниц", "ремесл", "craft", 
                                                 "artisan", "craftsman"]):
            keyword = random.choice(PEOPLE_HANDS_KEYWORDS)
            logger.info(f"👥 People enhancement: craftsmanship → {keyword[:50]}...")
            return keyword
        
        if any(word in text_lower for word in ["дегустац", "сомельє", "tasting", "sommelier"]):
            keyword = random.choice([
                "sommelier hands examining wine glass backlit dramatic",
                "wine tasting hands close up atmospheric moody",
                "hands holding wine glass elegant dark atmospheric"
            ])
            logger.info(f"👥 People enhancement: tasting → {keyword[:50]}...")
            return keyword
        
        return base_context
    
    def is_high_quality(self, photo: Dict) -> bool:
        """Validate photo quality based on multiple criteria"""
        likes = photo.get("likes", 0)
        if likes < 50:  # Reduced from 100 for more results
            return False
        
        width = photo.get("width", 0)
        height = photo.get("height", 0)
        if width < 1800 or height < 1000:  # Slightly reduced for more results
            return False
        
        description = (photo.get("description", "") or "").lower()
        alt_description = (photo.get("alt_description", "") or "").lower()
        
        for brand in BRAND_KEYWORDS:
            if brand in description or brand in alt_description:
                logger.warning(f"❌ Brand detected in photo: {brand}")
                return False
        
        photo_id = photo.get("id", "")
        if photo_id in self.used_image_ids:
            logger.info(f"⏭️ Skipping already used image: {photo_id}")
            return False
        
        return True
    
    def search_unsplash(self, query: str, per_page: int = 30) -> Optional[Dict]:
        """Search Unsplash with quality filtering"""
        if not self.access_key:
            logger.error("UNSPLASH_ACCESS_KEY not configured")
            return None
            
        headers = {"Authorization": f"Client-ID {self.access_key}"}
        params = {
            "query": query,
            "orientation": "landscape",
            "per_page": per_page,
            "order_by": "relevant"
        }
        
        try:
            response = requests.get(
                f"{UNSPLASH_API_URL}/search/photos",
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Unsplash API error: {response.status_code}")
                return None
            
            data = response.json()
            photos = data.get("results", [])
            
            if not photos:
                logger.warning(f"No photos found for query: {query[:50]}...")
                return None
            
            quality_photos = [p for p in photos if self.is_high_quality(p)]
            
            if quality_photos:
                selected = random.choice(quality_photos[:10])
                logger.info(f"✅ Quality photo selected (likes: {selected.get('likes', 0)})")
                return selected
            
            for photo in photos:
                photo_id = photo.get("id", "")
                if photo_id not in self.used_image_ids:
                    logger.warning("No high-quality photos, using first unused result")
                    return photo
            
            return None
            
        except Exception as e:
            logger.error(f"Error searching Unsplash: {str(e)}")
            return None
    
    def extract_photo_data(self, photo: Dict, query_used: str, tier: str) -> Dict:
        """Extract standardized data from Unsplash photo"""
        photographer = photo.get("user", {})
        photographer_name = photographer.get("name", "Unknown")
        photographer_url = photographer.get("links", {}).get("html", "")
        
        image_url = photo.get("urls", {}).get("regular", "")
        
        download_url = photo.get("links", {}).get("download_location", "")
        if download_url:
            self.trigger_download(download_url)
        
        attribution = f"Photo by {photographer_name} on Unsplash"
        
        return {
            'image_url': image_url,
            'unsplash_image_id': photo.get("id", ""),
            'image_credit': attribution,
            'image_credit_url': photographer_url,
            'image_photographer': photographer_name,
            'aesthetic_score': photo.get("likes", 0),
            'query_used': query_used,
            'query_method': f'premium_4tier_{tier}'
        }
    
    def trigger_download(self, download_location: str):
        """Trigger Unsplash download endpoint for attribution compliance"""
        if not download_location or not self.access_key:
            return
        try:
            headers = {"Authorization": f"Client-ID {self.access_key}"}
            requests.get(download_location, headers=headers, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to trigger download: {e}")
    
    def select_image_for_article(self, title: str, content: str) -> Optional[Dict]:
        """
        4-TIER INTELLIGENT SEARCH STRATEGY:
        
        Tier 0: Geographical (if country mentioned) 🌍
        Tier 1: Context-based with people enhancement 🏢
        Tier 2: HoReCa/Cocktail fallback 🍷
        Tier 3: Safe abstract premium 🎨
        
        Returns image data with attribution or None
        """
        db_used_ids = self.get_used_image_ids_from_db()
        self.used_image_ids = self.used_image_ids.union(db_used_ids)
        logger.info(f"📸 Premium image search starting, excluding {len(self.used_image_ids)} used images")
        
        full_text = f"{title} {content}"
        
        # ===== TIER 0: GEOGRAPHICAL =====
        geo_keyword = self.detect_country(full_text)
        if geo_keyword:
            photo = self.search_unsplash(geo_keyword)
            if photo:
                logger.info("✅ TIER 0 SUCCESS: Geographical image found")
                return self.extract_photo_data(photo, geo_keyword, "tier0_geo")
        
        # ===== TIER 1: CONTEXT-BASED =====
        base_context = self.interpret_context(title, content)
        
        if base_context:
            enhanced_context = self.enhance_context_with_people(base_context, full_text)
            photo = self.search_unsplash(enhanced_context)
            if photo:
                logger.info("✅ TIER 1 SUCCESS: Context-based image found")
                return self.extract_photo_data(photo, enhanced_context, "tier1_context")
        
        # Check for cocktail context specifically
        if any(word in full_text.lower() for word in ["коктейл", "cocktail", "бар", "bar", 
                                                        "міксолог", "mixolog", "bartender"]):
            cocktail_keyword = random.choice(COCKTAIL_KEYWORDS)
            logger.info(f"🍸 TIER 1.5: Trying cocktail search: {cocktail_keyword[:50]}...")
            photo = self.search_unsplash(cocktail_keyword)
            if photo:
                logger.info("✅ TIER 1.5 SUCCESS: Cocktail image found")
                return self.extract_photo_data(photo, cocktail_keyword, "tier1_cocktail")
        
        # ===== TIER 2: HORECA FALLBACK =====
        horeca_pool = HORECA_KEYWORDS + COCKTAIL_KEYWORDS[:5]
        horeca_keyword = random.choice(horeca_pool)
        
        logger.info(f"🍷 TIER 2: Trying HoReCa fallback: {horeca_keyword[:50]}...")
        photo = self.search_unsplash(horeca_keyword)
        if photo:
            logger.info("✅ TIER 2 SUCCESS: HoReCa image found")
            return self.extract_photo_data(photo, horeca_keyword, "tier2_horeca")
        
        # ===== TIER 3: SAFE ABSTRACT =====
        safe_keyword = random.choice(SAFE_FALLBACKS)
        logger.info(f"🎨 TIER 3: Trying safe abstract: {safe_keyword[:50]}...")
        photo = self.search_unsplash(safe_keyword)
        
        if photo:
            logger.info("✅ TIER 3 SUCCESS: Abstract image found")
            return self.extract_photo_data(photo, safe_keyword, "tier3_abstract")
        
        logger.error("❌ ALL TIERS FAILED: No image found")
        return None


unsplash_service = UnsplashService()
