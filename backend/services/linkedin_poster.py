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
            article_data: Dict with title, text, source_url, image_url, local_image_path, image_data (optional)
            
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
        local_image_path = article_data.get('local_image_path')
        image_data = article_data.get('image_data')  # Binary from database
        
        if image_url or local_image_path or image_data:
            return self._post_with_image(post_text, image_url, local_image_path, image_data)
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
    
    def _register_upload(self) -> Optional[Dict]:
        """
        Step 1: Register image upload with LinkedIn
        Returns upload URL and asset URN
        """
        url = f"{self.base_url}/{self.api_version}/assets?action=registerUpload"
        
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": self.organization_urn,
                "serviceRelationships": [{
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }]
            }
        }
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        try:
            logger.info("Registering image upload with LinkedIn...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                asset_urn = result.get('value', {}).get('asset')
                upload_url = result.get('value', {}).get('uploadMechanism', {}).get(
                    'com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest', {}
                ).get('uploadUrl')
                
                if asset_urn and upload_url:
                    logger.info(f"Upload registered: {asset_urn}")
                    return {
                        'asset_urn': asset_urn,
                        'upload_url': upload_url
                    }
                else:
                    logger.error(f"Invalid registration response: {result}")
                    return None
            else:
                logger.error(f"Registration failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to register upload: {e}")
            return None
    
    def _upload_image(self, upload_url: str, image_url: Optional[str] = None, local_image_path: Optional[str] = None, db_image_data: Optional[bytes] = None) -> bool:
        """
        Step 2: Upload image to LinkedIn
        Downloads image from URL, reads from local file, or uses database binary data
        
        Priority order:
        1. db_image_data (from database - most reliable for Render)
        2. local_image_path (for local development)
        3. image_url (likely expired - last resort)
        
        Args:
            upload_url: Pre-signed LinkedIn upload URL
            image_url: Remote image URL (last resort, likely expired)
            local_image_path: Local file path (for local dev)
            db_image_data: Binary image data from database (Render-persistent)
        
        Note: Pre-signed upload URL handles auth, don't add Authorization header
        """
        image_data = None
        content_type = 'image/png'
        
        # Priority 1: Use database image data (Render-persistent)
        if db_image_data:
            logger.info(f"✅ Using image from database ({len(db_image_data)} bytes)")
            image_data = db_image_data
            content_type = 'image/png'
        
        # Priority 2: Try local file
        if not image_data and local_image_path:
            try:
                import os
                if os.path.exists(local_image_path):
                    logger.info(f"Using local image: {local_image_path}")
                    with open(local_image_path, 'rb') as f:
                        image_data = f.read()
                    
                    # Determine content type from file extension
                    if local_image_path.lower().endswith('.png'):
                        content_type = 'image/png'
                    elif local_image_path.lower().endswith('.jpg') or local_image_path.lower().endswith('.jpeg'):
                        content_type = 'image/jpeg'
                    
                    logger.info(f"Loaded local image (Content-Type: {content_type})")
                else:
                    logger.warning(f"Local image path not found: {local_image_path}")
            except Exception as e:
                logger.error(f"Failed to read local image: {e}")
        
        # Priority 3: Try remote URL (usually expired)
        if not image_data and image_url:
            try:
                logger.warning(f"Trying remote URL (may be expired): {image_url}")
                img_response = requests.get(image_url, timeout=30)
                
                if img_response.status_code == 200:
                    # Validate it's actually an image
                    response_content_type = img_response.headers.get('Content-Type', '')
                    if 'image' in response_content_type:
                        image_data = img_response.content
                        content_type = response_content_type
                        logger.info(f"Downloaded from remote URL (Content-Type: {content_type})")
                    else:
                        logger.warning(f"Remote URL returned non-image Content-Type: {response_content_type}")
                else:
                    logger.warning(f"Failed to download from remote URL: {img_response.status_code}")
            except Exception as e:
                logger.warning(f"Exception downloading from remote URL: {e}")
        
        # If we still don't have image data, fail
        if not image_data:
            logger.error("No valid image data available from database, local file, or remote URL")
            return False
        
        # Upload to LinkedIn
        try:
            logger.info(f"Uploading image to LinkedIn (size: {len(image_data)} bytes)...")
            
            # Pre-signed URL handles auth - no Authorization header needed
            headers = {
                "Content-Type": content_type
            }
            
            upload_response = requests.put(
                upload_url,
                data=image_data,
                headers=headers,
                timeout=60
            )
            
            if upload_response.status_code in [200, 201]:
                logger.info("Image uploaded successfully to LinkedIn")
                return True
            else:
                logger.error(f"LinkedIn upload failed: {upload_response.status_code} - {upload_response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception during LinkedIn upload: {e}")
            return False
    
    def _post_with_image(self, text: str, image_url: Optional[str] = None, local_image_path: Optional[str] = None, db_image_data: Optional[bytes] = None) -> Dict:
        """
        Post content with image to LinkedIn using proper asset upload workflow
        
        Steps:
        1. Register upload to get asset URN
        2. Upload image binary (priority: database > local file > URL)
        3. Create post with asset URN
        4. If image upload fails, degrades to text-only post
        
        Args:
            text: Post text content
            image_url: Remote image URL (optional, likely expired)
            local_image_path: Local image file path (optional)
            db_image_data: Binary image data from database (Render-persistent)
        """
        
        # Step 1: Register upload
        upload_info = self._register_upload()
        if not upload_info:
            logger.warning("Image upload registration failed, posting text-only")
            return self._post_text_only(text)
        
        # Step 2: Upload image (priority: database > local > URL)
        upload_success = self._upload_image(upload_info['upload_url'], image_url, local_image_path, db_image_data)
        if not upload_success:
            logger.warning("Image upload failed, degrading to text-only post")
            return self._post_text_only(text)
        
        # Step 3: Create post with asset URN
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
                        "media": upload_info['asset_urn'],
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
            logger.info("Creating LinkedIn post with uploaded image...")
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
