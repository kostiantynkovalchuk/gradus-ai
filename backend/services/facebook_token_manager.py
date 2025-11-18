import os
import requests
import logging
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

class FacebookTokenManager:
    def __init__(self):
        self.app_id = os.getenv('FACEBOOK_APP_ID', '1033029015627449')
        self.app_secret = os.getenv('FACEBOOK_APP_SECRET')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.current_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.graph_api_version = 'v18.0'
    
    def check_token_expiration(self) -> Dict:
        """
        Check when current token expires
        Returns dict with expiration info
        """
        if not self.current_token or not self.app_secret:
            return {"error": "Token or app secret not configured"}
        
        url = f"https://graph.facebook.com/{self.graph_api_version}/debug_token"
        params = {
            'input_token': self.current_token,
            'access_token': f"{self.app_id}|{self.app_secret}"
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            result = response.json()
            
            if 'data' in result:
                token_data = result['data']
                expires_at = token_data.get('expires_at', 0)
                data_access_expires_at = token_data.get('data_access_expires_at', 0)
                
                if expires_at == 0:
                    status = "never_expires"
                    days_remaining = None
                else:
                    expiry_date = datetime.fromtimestamp(expires_at)
                    days_remaining = (expiry_date - datetime.now()).days
                    status = "expires_soon" if days_remaining < 7 else "healthy"
                
                return {
                    "status": status,
                    "is_valid": token_data.get('is_valid', False),
                    "expires_at": expires_at,
                    "data_access_expires_at": data_access_expires_at,
                    "days_remaining": days_remaining,
                    "needs_refresh": days_remaining is not None and days_remaining < 7
                }
            else:
                return {"error": "Invalid token response", "details": result}
                
        except Exception as e:
            logger.error(f"Failed to check token: {e}")
            return {"error": str(e)}
    
    def send_expiration_alert(self, days_remaining: int):
        """Send Telegram alert when token is expiring soon"""
        message = f"""🚨 <b>Facebook Token Alert</b>

⏰ Your Facebook Page Access Token expires in <b>{days_remaining} days</b>!

📋 Action needed:
1. Go to: developers.facebook.com/tools/accesstoken
2. Generate new Page Token for Gradus Media
3. Update FACEBOOK_PAGE_ACCESS_TOKEN in Replit Secrets

🔗 Quick link: https://developers.facebook.com/tools/accesstoken

Without renewal, Facebook posting will stop working!"""
        
        try:
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            
            if bot_token and chat_id:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
                requests.post(url, json=payload, timeout=10)
                logger.info(f"Token expiration alert sent ({days_remaining} days)")
        except Exception as e:
            logger.error(f"Failed to send expiration alert: {e}")

facebook_token_manager = FacebookTokenManager()
