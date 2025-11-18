import os
import requests
from typing import Dict, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class FacebookPoster:
    def __init__(self):
        self.page_access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.graph_api_version = 'v18.0'
        self.base_url = f'https://graph.facebook.com/{self.graph_api_version}'
    
    def format_post_text(self, article_data: Dict) -> str:
        """
        Format post text for Facebook
        
        Args:
            article_data: Dict with title, content, source, author
            
        Returns:
            Formatted post text
        """
        title = article_data.get('translated_title', '')
        content = article_data.get('translated_content', '')[:500]
        source = article_data.get('source', 'The Spirits Business')
        author = article_data.get('author', '')
        original_url = article_data.get('url', '')
        
        post_text = f"""📰 {title}

{content}...

🔗 Читати повністю: {original_url}
📰 {source}"""
        
        if author:
            post_text += f"\n✍️ {author}"
        
        return post_text
    
    def post_with_image(self, article_data: Dict) -> Optional[Dict]:
        """
        Post to Facebook Page with image
        
        Args:
            article_data: Dict with all article info including image_url
            
        Returns:
            Dict with post_id and post_url, or None if failed
        """
        if not self.page_access_token or not self.page_id:
            logger.error("Facebook credentials not configured")
            return None
        
        message = self.format_post_text(article_data)
        image_url = article_data.get('image_url')
        
        if not image_url:
            logger.warning("No image URL provided, posting text only")
            return self.post_text_only(message)
        
        url = f"{self.base_url}/{self.page_id}/photos"
        
        payload = {
            'message': message,
            'url': image_url,
            'access_token': self.page_access_token
        }
        
        try:
            response = requests.post(url, data=payload, timeout=30)
            result = response.json()
            
            if 'id' in result:
                post_id = result['id']
                post_url = f"https://www.facebook.com/{self.page_id}/posts/{post_id.split('_')[1]}"
                
                logger.info(f"Posted to Facebook successfully: {post_id}")
                
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
            response = requests.post(url, data=payload, timeout=30)
            result = response.json()
            
            if 'id' in result:
                post_id = result['id']
                post_url = f"https://www.facebook.com/{self.page_id}/posts/{post_id.split('_')[1]}"
                
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
