import os
import requests
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class LinkedInPoster:
    """
    LinkedIn Organization Page posting service
    Requires OAuth 2.0 access token with w_organization_social scope
    """
    
    def __init__(self):
        self.access_token = os.getenv('LINKEDIN_ACCESS_TOKEN')
        self.organization_urn = os.getenv('LINKEDIN_ORGANIZATION_URN')
        self.api_version = 'v2'
        self.base_url = 'https://api.linkedin.com'
        
    def format_post_text(self, article_data: Dict) -> str:
        """
        Format post text for LinkedIn with Ukrainian content
        
        Args:
            article_data: Dict with title, text, source, url
            
        Returns:
            Formatted post text
        """
        title = article_data.get('title', '')
        text = article_data.get('text', '')
        source = article_data.get('source', 'The Spirits Business')
        source_url = article_data.get('source_url', '')
        
        post_text = f"""{title}

{text}

📰 {source}"""
        
        if source_url:
            post_text += f"\n🔗 {source_url}"
        
        return post_text
    
    def post_to_linkedin(self, article_data: Dict) -> Dict:
        """
        Post content to LinkedIn organization page
        
        Args:
            article_data: Dict with title, text, source_url, image_url (optional)
            
        Returns:
            Dict with status, post_id, post_url
        """
        if not self.access_token:
            logger.error("LinkedIn access token not configured")
            return {
                'status': 'error',
                'message': 'LinkedIn access token missing',
                'action_required': 'Set LINKEDIN_ACCESS_TOKEN in Replit Secrets'
            }
        
        if not self.organization_urn:
            logger.error("LinkedIn organization URN not configured")
            return {
                'status': 'error',
                'message': 'LinkedIn organization URN missing',
                'action_required': 'Set LINKEDIN_ORGANIZATION_URN in Replit Secrets'
            }
        
        post_text = self.format_post_text(article_data)
        image_url = article_data.get('image_url')
        
        if image_url:
            return self._post_with_image(post_text, image_url)
        else:
            return self._post_text_only(post_text)
    
    def _post_text_only(self, text: str) -> Dict:
        """Post text-only content to LinkedIn"""
        
        url = f"{self.base_url}/{self.api_version}/ugcPosts"
        
        payload = {
            "author": self.organization_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": text
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        try:
            logger.info("Posting text to LinkedIn...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            return self._parse_response(response)
            
        except Exception as e:
            logger.error(f"Failed to post to LinkedIn: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _post_with_image(self, text: str, image_url: str) -> Dict:
        """Post content with image to LinkedIn"""
        
        url = f"{self.base_url}/{self.api_version}/ugcPosts"
        
        payload = {
            "author": self.organization_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": text
                    },
                    "shareMediaCategory": "IMAGE",
                    "media": [{
                        "status": "READY",
                        "description": {
                            "text": "Article image"
                        },
                        "media": image_url,
                        "title": {
                            "text": "Image"
                        }
                    }]
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        try:
            logger.info("Posting with image to LinkedIn...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            return self._parse_response(response)
            
        except Exception as e:
            logger.error(f"Failed to post to LinkedIn: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _parse_response(self, response) -> Dict:
        """Parse LinkedIn API response"""
        
        logger.info(f"LinkedIn API response: {response.status_code}")
        
        if response.status_code == 201:
            result = response.json()
            post_id = result.get('id', '')
            
            post_url = f"https://www.linkedin.com/feed/update/{post_id}"
            
            logger.info(f"Posted to LinkedIn successfully: {post_id}")
            
            return {
                'status': 'success',
                'post_id': post_id,
                'post_url': post_url,
                'posted_at': datetime.now().isoformat()
            }
        else:
            error_msg = response.text
            logger.error(f"LinkedIn API error: {error_msg}")
            
            if response.status_code == 401:
                return {
                    'status': 'error',
                    'message': 'LinkedIn access token invalid or expired',
                    'action_required': 'Refresh LINKEDIN_ACCESS_TOKEN'
                }
            elif response.status_code == 403:
                return {
                    'status': 'error',
                    'message': 'Permission denied - check organization access and scopes',
                    'action_required': 'Verify app has w_organization_social scope and you are org admin'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'LinkedIn API error ({response.status_code}): {error_msg}'
                }
    
    def verify_token(self) -> bool:
        """
        Verify that the access token is valid and has proper permissions
        """
        if not self.access_token:
            return False
        
        url = f"{self.base_url}/v2/userinfo"
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                logger.info("LinkedIn token is valid")
                return True
            else:
                logger.error(f"LinkedIn token invalid: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return False

linkedin_poster = LinkedInPoster()
