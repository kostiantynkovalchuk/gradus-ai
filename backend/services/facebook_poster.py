import os
import requests
from typing import Dict, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def get_backend_url() -> str:
    """Get the public backend URL for image serving"""
    return os.getenv('APP_URL') or os.getenv('BACKEND_URL') or 'https://gradus-ai.onrender.com'

class FacebookPoster:
    def __init__(self):
        self.page_access_token = os.getenv('FACEBOOK_ACCESS_TOKEN') or os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.graph_api_version = 'v18.0'
        self.base_url = f'https://graph.facebook.com/{self.graph_api_version}'
    
    def format_post_text(self, article_data: Dict) -> str:
        """
        Format post text for Facebook with FULL Ukrainian content
        
        Args:
            article_data: Dict with title, content, source, author, image_credit
            
        Returns:
            Formatted post text with Unsplash attribution if applicable
        """
        title = article_data.get('translated_title', '')
        content = article_data.get('translated_content', '')
        source = article_data.get('source', 'The Spirits Business')
        author = article_data.get('author', '')
        image_credit = article_data.get('image_credit', '')
        
        post_text = f"""📰 {title}

{content}

📰 {source}"""
        
        if author:
            post_text += f"\n✍️ {author}"
        
        if image_credit:
            post_text += f"\n\n📷 {image_credit}"
        
        return post_text
    
    def post_with_image(self, article_data: Dict) -> Optional[Dict]:
        """
        Post to Facebook Page with image
        
        Priority order for image source:
        1. image_data (binary from database - upload directly)
        2. database_image_url (public /api/images/serve endpoint - Facebook fetches from our server)
        3. local_image_path (for local development)
        4. image_url (DALL-E URL - likely expired, last resort)
        
        Args:
            article_data: Dict with all article info including image_data, image_url, article_id, or local_image_path
            
        Returns:
            Dict with post_id and post_url, or None if failed
        """
        if not self.page_access_token or not self.page_id:
            logger.error("Facebook credentials not configured")
            return None
        
        message = self.format_post_text(article_data)
        image_data = article_data.get('image_data')  # Binary data from database
        article_id = article_data.get('article_id')  # For public image URL
        local_image_path = article_data.get('local_image_path')
        image_url = article_data.get('image_url')  # DALL-E URL (usually expired)
        
        # Priority 1: Use image_data from database (direct upload)
        if image_data:
            logger.info(f"✅ [Priority 1] Using image from database ({len(image_data)} bytes)")
            result = self._post_with_image_data(message, image_data)
            if result:
                return result
            logger.warning("⚠️  Database image upload failed, trying public URL...")
        
        # Priority 2: Use public database image URL (Facebook fetches from our server)
        if article_id:
            backend_url = get_backend_url()
            public_image_url = f"{backend_url}/api/images/serve/{article_id}"
            logger.info(f"✅ [Priority 2] Using public image URL: {public_image_url}")
            result = self._post_with_image_url(message, public_image_url)
            if result:
                return result
            logger.warning("⚠️  Public image URL failed, trying local file...")
        
        # Priority 3: Try local image file (for local development)
        found_path = None
        if local_image_path:
            if os.path.exists(local_image_path):
                found_path = local_image_path
                logger.info(f"✅ [Priority 3] Using local image (absolute): {local_image_path}")
            elif os.path.exists(os.path.join(os.getcwd(), local_image_path)):
                found_path = os.path.join(os.getcwd(), local_image_path)
                logger.info(f"✅ [Priority 3] Using local image (relative): {found_path}")
            else:
                logger.warning(f"⚠️  Local image path not found: {local_image_path}")
        
        if found_path:
            result = self._post_with_local_image(message, found_path)
            if result:
                return result
            logger.warning("⚠️  Local image posting failed, trying DALL-E URL...")
        
        # Priority 4: Try original image URL (DALL-E - usually expired but worth a try)
        if image_url:
            logger.warning("⚠️  [Priority 4] Trying DALL-E URL (may be expired)")
            result = self._post_with_image_url(message, image_url)
            if result:
                return result
            logger.warning("⚠️  DALL-E URL failed (likely expired), posting text-only as fallback...")
            return self.post_text_only(message)
        else:
            logger.warning("No image source available, posting text only")
            return self.post_text_only(message)
    
    def _post_with_image_data(self, message: str, image_data: bytes) -> Optional[Dict]:
        """Post to Facebook using binary image data from database (Render-compatible)"""
        url = f"{self.base_url}/{self.page_id}/photos"
        
        try:
            from io import BytesIO
            
            # Create a file-like object from bytes
            image_file = BytesIO(image_data)
            image_file.name = 'image.png'  # Facebook needs a filename
            
            files = {'source': ('image.png', image_file, 'image/png')}
            data = {
                'message': message,
                'access_token': self.page_access_token
            }
            
            logger.info(f"Posting to Facebook with database image ({len(image_data)} bytes)...")
            response = requests.post(url, files=files, data=data, timeout=30)
            result = response.json()
            
            return self._parse_facebook_response(result)
            
        except Exception as e:
            logger.error(f"Failed to post with database image: {e}")
            logger.exception("Full traceback:")
            return None
    
    def _post_with_local_image(self, message: str, local_image_path: str) -> Optional[Dict]:
        """Post to Facebook using local image file (prevents expiration issues)"""
        url = f"{self.base_url}/{self.page_id}/photos"
        
        try:
            with open(local_image_path, 'rb') as image_file:
                files = {'source': image_file}
                data = {
                    'message': message,
                    'access_token': self.page_access_token
                }
                
                logger.info(f"Posting to Facebook with local image file...")
                response = requests.post(url, files=files, data=data, timeout=30)
                result = response.json()
                
                return self._parse_facebook_response(result)
                
        except Exception as e:
            logger.error(f"Failed to post with local image: {e}")
            logger.exception("Full traceback:")
            return None
    
    def _post_with_image_url(self, message: str, image_url: str) -> Optional[Dict]:
        """Post to Facebook using image URL (may fail if URL expired)"""
        url = f"{self.base_url}/{self.page_id}/photos"
        
        payload = {
            'message': message,
            'url': image_url,
            'access_token': self.page_access_token
        }
        
        try:
            logger.info(f"Posting to Facebook with image URL: {image_url[:100]}...")
            response = requests.post(url, data=payload, timeout=30)
            result = response.json()
            
            return self._parse_facebook_response(result)
                
        except Exception as e:
            logger.error(f"Failed to post with image URL: {e}")
            logger.exception("Full traceback:")
            return None
    
    def _parse_facebook_response(self, result: Dict) -> Optional[Dict]:
        """Parse Facebook API response and return post data"""
        logger.info(f"Facebook API response: {result}")
        
        if 'id' in result:
            post_id = result['id']
            
            try:
                if '_' in post_id:
                    post_number = post_id.split('_')[1]
                else:
                    post_number = post_id
                
                post_url = f"https://www.facebook.com/{self.page_id}/posts/{post_number}"
            except Exception as parse_error:
                logger.error(f"Error parsing post_id '{post_id}': {parse_error}")
                post_url = f"https://www.facebook.com/{self.page_id}"
            
            logger.info(f"Posted to Facebook successfully: {post_id}")
            
            return {
                'post_id': post_id,
                'post_url': post_url,
                'posted_at': datetime.now().isoformat()
            }
        else:
            logger.error(f"Facebook API error: {result}")
            
            if 'error' in result:
                error = result['error']
                logger.error(f"Facebook error code {error.get('code')}: {error.get('message')}")
                
                if error.get('code') == 190:
                    logger.error("Facebook access token is invalid or expired!")
                elif error.get('code') == 324:
                    logger.error("Image file missing or invalid - URL may have expired!")
            
            return None
    
    def post_text_only(self, message: str) -> Optional[Dict]:
        """
        Post text-only to Facebook Page (fallback if no image)
        """
        url = f"{self.base_url}/{self.page_id}/feed"
        
        payload = {
            'message': message,
            'access_token': self.page_access_token
        }
        
        try:
            logger.info(f"Posting text-only to Facebook...")
            response = requests.post(url, data=payload, timeout=30)
            result = response.json()
            
            logger.info(f"Facebook API response: {result}")
            
            if 'id' in result:
                post_id = result['id']
                
                try:
                    if '_' in post_id:
                        post_number = post_id.split('_')[1]
                    else:
                        post_number = post_id
                    
                    post_url = f"https://www.facebook.com/{self.page_id}/posts/{post_number}"
                except Exception as parse_error:
                    logger.error(f"Error parsing post_id '{post_id}': {parse_error}")
                    post_url = f"https://www.facebook.com/{self.page_id}"
                
                logger.info(f"Posted text to Facebook successfully: {post_id}")
                
                return {
                    'post_id': post_id,
                    'post_url': post_url,
                    'posted_at': datetime.now().isoformat()
                }
            else:
                logger.error(f"Facebook API error: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to post to Facebook: {e}")
            logger.exception("Full traceback:")
            return None
    
    def verify_token(self) -> bool:
        """
        Verify that the access token is valid
        """
        if not self.page_access_token:
            return False
        
        url = f"{self.base_url}/me"
        params = {'access_token': self.page_access_token}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            result = response.json()
            
            if 'id' in result:
                logger.info(f"Facebook token valid for page: {result.get('name')}")
                return True
            else:
                logger.error(f"Invalid token: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return False

facebook_poster = FacebookPoster()
