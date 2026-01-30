"""
Unsplash API Integration for Article Images
Replaces DALL-E with authentic photography for social media compliance
"""
import os
import requests
import logging
from typing import Dict, List, Optional
import re

logger = logging.getLogger(__name__)

UNSPLASH_API_URL = "https://api.unsplash.com"

BUSINESS_TERMS = {
    'uk': ['угода', 'партнерство', 'інвестиції', 'злиття', 'придбання', 'контракт', 'угоду', 'партнерства'],
    'en': ['deal', 'partnership', 'investment', 'acquisition', 'merger', 'contract', 'agreement']
}

GEOGRAPHY_TERMS = {
    'uk': {
        'україна': 'ukraine kyiv',
        'франція': 'france paris',
        'італія': 'italy rome',
        'іспанія': 'spain barcelona',
        'шотландія': 'scotland edinburgh',
        'ірландія': 'ireland dublin',
        'японія': 'japan tokyo',
        'мексика': 'mexico',
        'аргентина': 'argentina',
        'німеччина': 'germany',
        'великобританія': 'uk london',
        'сша': 'usa',
        'китай': 'china',
        'австралія': 'australia'
    },
    'en': {
        'ukraine': 'ukraine kyiv',
        'france': 'france paris',
        'italy': 'italy rome',
        'spain': 'spain barcelona',
        'scotland': 'scotland edinburgh',
        'ireland': 'ireland dublin',
        'japan': 'japan tokyo',
        'mexico': 'mexico',
        'argentina': 'argentina',
        'germany': 'germany',
        'uk': 'uk london',
        'usa': 'usa',
        'china': 'china',
        'australia': 'australia'
    }
}

SPIRITS_TERMS = {
    'uk': ['віскі', 'коньяк', 'горілка', 'джин', 'текіла', 'вино', 'сідр', 'ром', 'бренді', 'лікер', 'шампанське', 'пиво', 'бурбон'],
    'en': ['whisky', 'whiskey', 'cognac', 'vodka', 'gin', 'tequila', 'wine', 'cider', 'rum', 'brandy', 'liqueur', 'champagne', 'beer', 'bourbon', 'soju', 'sake']
}

PREMIUM_TERMS = ['преміум', 'luxury', 'craft', 'artisan', 'exclusive', 'boutique', 'premium', 'елітний', 'ексклюзив']

BUSINESS_QUERIES = [
    "luxury boardroom meeting",
    "business handshake premium",
    "executive office modern",
    "corporate meeting professional"
]

CRAFT_QUERIES = [
    "whiskey barrel cellar craftsmanship",
    "artisan distillery copper stills",
    "oak barrel aging room",
    "vineyard premium winery",
    "wine cellar luxury",
    "craft brewery interior"
]

HORECA_QUERIES = [
    "luxury hotel bar interior",
    "premium restaurant ambiance",
    "exclusive cocktail lounge",
    "fine dining atmosphere",
    "craft cocktail artisan",
    "upscale bar interior",
    "hotel lobby bar",
    "wine bar elegant"
]


class UnsplashService:
    def __init__(self):
        self.access_key = os.getenv("UNSPLASH_ACCESS_KEY")
        if not self.access_key:
            logger.warning("UNSPLASH_ACCESS_KEY not set - image fetching will not work")
        self.headers = {
            "Authorization": f"Client-ID {self.access_key}"
        }
        self.used_image_ids = set()
    
    def extract_image_keywords(self, title: str, content: str) -> Dict:
        """
        Analyze article title + content and extract context for image search.
        Returns dict with detected categories.
        """
        text = f"{title} {content}".lower()
        
        context = {
            'has_business': False,
            'has_geography': None,
            'has_spirits': False,
            'has_premium': False,
            'geography_query': None,
            'detected_terms': []
        }
        
        for lang in ['uk', 'en']:
            for term in BUSINESS_TERMS[lang]:
                if term in text:
                    context['has_business'] = True
                    context['detected_terms'].append(f"business:{term}")
                    break
        
        for lang in ['uk', 'en']:
            for term, query in GEOGRAPHY_TERMS[lang].items():
                if term in text:
                    context['has_geography'] = term
                    context['geography_query'] = query
                    context['detected_terms'].append(f"geo:{term}")
                    break
            if context['has_geography']:
                break
        
        for lang in ['uk', 'en']:
            for term in SPIRITS_TERMS[lang]:
                if term in text:
                    context['has_spirits'] = True
                    context['detected_terms'].append(f"spirits:{term}")
                    break
        
        for term in PREMIUM_TERMS:
            if term in text:
                context['has_premium'] = True
                context['detected_terms'].append(f"premium:{term}")
                break
        
        logger.info(f"Extracted context: {context['detected_terms']}")
        return context
    
    def build_search_queries(self, context: Dict) -> List[str]:
        """
        Build prioritized search queries based on extracted context.
        """
        queries = []
        
        if context['has_business']:
            queries.extend(BUSINESS_QUERIES[:2])
        
        if context['has_geography'] and context['geography_query']:
            geo = context['geography_query']
            queries.extend([
                f"{geo} landscape architecture",
                f"{geo} cityscape premium"
            ])
        
        if context['has_spirits']:
            queries.extend(CRAFT_QUERIES[:3])
        
        queries.extend(HORECA_QUERIES)
        
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        
        return unique_queries[:10]
    
    def fetch_unsplash_images(self, queries: List[str], limit: int = 5) -> List[Dict]:
        """
        Fetch images from Unsplash API based on search queries.
        Returns list of image data with attribution info.
        """
        if not self.access_key:
            logger.error("Unsplash API key not configured")
            return []
        
        images = []
        
        for query in queries:
            if len(images) >= limit:
                break
            
            try:
                response = requests.get(
                    f"{UNSPLASH_API_URL}/search/photos",
                    headers=self.headers,
                    params={
                        "query": query,
                        "per_page": 10,
                        "orientation": "landscape",
                        "content_filter": "high"
                    },
                    timeout=10
                )
                
                if response.status_code == 429:
                    logger.warning("Unsplash rate limit reached")
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                for photo in data.get('results', []):
                    if photo['id'] in self.used_image_ids:
                        continue
                    
                    likes = photo.get('likes', 0)
                    user = photo.get('user', {})
                    for_hire = user.get('for_hire', False)
                    
                    if likes >= 500 or for_hire:
                        image_data = {
                            'id': photo['id'],
                            'url': photo['urls']['regular'],
                            'download_url': photo['links']['download_location'],
                            'photographer_name': user.get('name', 'Unknown'),
                            'photographer_url': user.get('links', {}).get('html', 'https://unsplash.com'),
                            'photographer_username': user.get('username', ''),
                            'likes': likes,
                            'description': photo.get('description') or photo.get('alt_description') or '',
                            'query_used': query
                        }
                        
                        images.append(image_data)
                        self.used_image_ids.add(photo['id'])
                        
                        if len(images) >= limit:
                            break
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Unsplash API error for query '{query}': {e}")
                continue
        
        logger.info(f"Fetched {len(images)} images from Unsplash")
        return images
    
    def trigger_download(self, download_url: str) -> bool:
        """
        Trigger download endpoint to track image usage (Unsplash API requirement).
        This compensates photographers.
        """
        if not self.access_key:
            return False
        
        try:
            response = requests.get(
                download_url,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            logger.info("Unsplash download tracked successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to track Unsplash download: {e}")
            return False
    
    def format_attribution(self, photographer_name: str, photographer_url: str) -> Dict:
        """
        Format proper attribution as required by Unsplash API Terms Section 9.
        """
        credit_text = f"Photo by {photographer_name} on Unsplash"
        credit_html = f'<a href="{photographer_url}">{photographer_name}</a> on <a href="https://unsplash.com">Unsplash</a>'
        
        return {
            'credit_text': credit_text,
            'credit_html': credit_html,
            'photographer_name': photographer_name,
            'photographer_url': photographer_url
        }
    
    def get_used_image_ids_from_db(self) -> set:
        """
        Query database for previously used Unsplash image IDs to prevent duplicates.
        """
        try:
            from database import SessionLocal
            from models.content import ContentQueue
            
            db = SessionLocal()
            try:
                used_ids = db.query(ContentQueue.unsplash_image_id).filter(
                    ContentQueue.unsplash_image_id != None
                ).all()
                return {row[0] for row in used_ids if row[0]}
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not query DB for used image IDs: {e}")
            return set()
    
    def select_image_for_article(self, title: str, content: str) -> Optional[Dict]:
        """
        Complete pipeline: extract keywords, build queries, fetch images, select best one.
        Returns image data with attribution or None if no suitable image found.
        """
        db_used_ids = self.get_used_image_ids_from_db()
        self.used_image_ids = self.used_image_ids.union(db_used_ids)
        logger.info(f"Excluding {len(self.used_image_ids)} previously used images")
        
        context = self.extract_image_keywords(title, content)
        queries = self.build_search_queries(context)
        
        logger.info(f"Searching Unsplash with queries: {queries[:3]}...")
        
        images = self.fetch_unsplash_images(queries, limit=5)
        
        if not images:
            logger.warning("No suitable images found from Unsplash")
            return None
        
        selected = images[0]
        
        self.trigger_download(selected['download_url'])
        
        attribution = self.format_attribution(
            selected['photographer_name'],
            selected['photographer_url']
        )
        
        return {
            'image_url': selected['url'],
            'unsplash_image_id': selected['id'],
            'image_credit': attribution['credit_text'],
            'image_credit_url': selected['photographer_url'],
            'image_photographer': selected['photographer_name'],
            'all_images': images
        }


unsplash_service = UnsplashService()
