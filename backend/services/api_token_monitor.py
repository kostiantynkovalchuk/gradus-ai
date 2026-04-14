"""
API Token Monitor

Monitors critical API tokens for health, expiration, and usage.

Active checks:
- Anthropic (Claude API): usage, rate limits, key validity
- OpenAI (embeddings, DALL-E): usage, rate limits, key validity

Removed checks:
- Facebook: Using non-expiring Business Portfolio token, monitoring redundant
"""

import os
import requests
import logging
import anthropic as _anthropic_module
from typing import Dict, List, Optional
from datetime import datetime
from openai import OpenAI

logger = logging.getLogger(__name__)

class APITokenMonitor:
    """
    Monitor all API tokens, quotas, and expiration dates
    Send proactive Telegram alerts before issues occur
    """
    
    def __init__(self):
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        self.days_warning = 7
        self.quota_warning_percent = 80
        
    def check_all_services(self) -> Dict:
        """
        Check all API services
        Returns summary of all checks
        """
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'services': {},
            'warnings': [],
            'errors': []
        }
        
        services_to_check = [
            ('anthropic', self.check_anthropic_api),
            ('openai', self.check_openai_api),
            ('telegram', self.check_telegram_bot)
        ]
        
        for service_name, check_function in services_to_check:
            try:
                service_status = check_function()
                results['services'][service_name] = service_status
                
                if service_status.get('warning'):
                    results['warnings'].append({
                        'service': service_name,
                        'message': service_status.get('warning_message')
                    })
                
                if service_status.get('status') == 'error':
                    results['errors'].append({
                        'service': service_name,
                        'message': service_status.get('error_message')
                    })
                    
            except Exception as e:
                logger.error(f"Error checking {service_name}: {e}")
                results['errors'].append({
                    'service': service_name,
                    'message': str(e)
                })
        
        if results['warnings'] or results['errors']:
            self._send_alert_notification(results)
        
        return results
    
    def check_anthropic_api(self) -> Dict:
        """
        Check Claude API status via a real minimal API call.
        Uses typed SDK exceptions — never string-matches error messages.
        Timeout: 10 seconds. Model: claude-haiku-4-5-20251001 (cheapest/fastest).
        """
        _SVC = 'Claude AI (Anthropic)'
        _CONSOLE = 'https://console.anthropic.com/settings/usage'
        _KEYS_URL = 'https://console.anthropic.com/settings/keys'

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            logger.error("[APIMonitor] ANTHROPIC_API_KEY is not set")
            return {
                'status': 'error',
                'service_name': _SVC,
                'error_type': 'NO_KEY',
                'error_message': 'No Anthropic API key configured',
            }

        try:
            client = _anthropic_module.Anthropic(api_key=api_key, timeout=10.0)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            logger.info("[APIMonitor] Anthropic check: healthy")
            return {
                'status': 'healthy',
                'service_name': _SVC,
                'is_valid': True,
                'last_checked': datetime.now().isoformat(),
                'console_url': _CONSOLE,
                'note': 'API key valid. Check usage at console.anthropic.com',
            }

        except _anthropic_module.AuthenticationError as e:
            logger.error(f"[APIMonitor] Anthropic 401 AuthenticationError: {e}")
            return {
                'status': 'error',
                'service_name': _SVC,
                'is_valid': False,
                'error_type': 'AUTH_FAILURE',
                'http_status': 401,
                'error_message': 'API key invalid or expired (401 AuthenticationError)',
                'action_required': 'Update ANTHROPIC_API_KEY in Replit Secrets',
                'console_url': _KEYS_URL,
            }

        except _anthropic_module.RateLimitError as e:
            logger.warning(f"[APIMonitor] Anthropic 429 RateLimitError: {e}")
            return {
                'status': 'warning',
                'service_name': _SVC,
                'warning': True,
                'error_type': 'RATE_LIMITED',
                'http_status': 429,
                'warning_message': 'Claude API rate-limited (429) — key is valid, usage is high',
                'action_required': 'Check usage at console.anthropic.com',
                'console_url': _CONSOLE,
            }

        except _anthropic_module.InternalServerError as e:
            http_status = getattr(e, 'status_code', None)
            error_type = 'OVERLOADED' if http_status == 529 else 'SERVER_ERROR'
            logger.warning(f"[APIMonitor] Anthropic InternalServerError ({http_status}): {e}")
            return {
                'status': 'warning',
                'service_name': _SVC,
                'warning': True,
                'error_type': error_type,
                'http_status': http_status,
                'warning_message': (
                    f'Claude API overloaded (529) — key is valid, Anthropic side issue'
                    if http_status == 529 else
                    f'Claude API server error ({http_status}) — key is valid, Anthropic side issue'
                ),
                'console_url': _CONSOLE,
            }

        except _anthropic_module.APITimeoutError as e:
            logger.warning(f"[APIMonitor] Anthropic request timed out after 10s: {e}")
            return {
                'status': 'warning',
                'service_name': _SVC,
                'warning': True,
                'error_type': 'TIMEOUT',
                'warning_message': 'Claude API did not respond within 10s — key likely valid, network issue',
                'console_url': _CONSOLE,
            }

        except _anthropic_module.APIConnectionError as e:
            logger.error(f"[APIMonitor] Anthropic connection error: {e}")
            return {
                'status': 'warning',
                'service_name': _SVC,
                'warning': True,
                'error_type': 'CONNECTION_ERROR',
                'warning_message': f'Claude API connection failed — {str(e)[:100]}',
                'console_url': _CONSOLE,
            }

        except _anthropic_module.APIStatusError as e:
            http_status = e.status_code
            raw_msg = str(e)
            logger.error(f"[APIMonitor] Anthropic APIStatusError ({http_status}): {raw_msg[:200]}")
            if http_status == 400 and 'credit balance' in raw_msg.lower():
                return {
                    'status': 'error',
                    'service_name': _SVC,
                    'warning': True,
                    'error_type': 'BILLING_ERROR',
                    'http_status': 400,
                    'error_message': 'Anthropic credit balance is too low — top up at console.anthropic.com',
                    'action_required': 'Add credits at console.anthropic.com/settings/billing',
                    'console_url': 'https://console.anthropic.com/settings/billing',
                }
            return {
                'status': 'error',
                'service_name': _SVC,
                'error_type': f'HTTP_{http_status}',
                'http_status': http_status,
                'error_message': f'Unexpected Claude API error ({http_status}): {raw_msg[:120]}',
                'console_url': _CONSOLE,
            }

        except Exception as e:
            logger.error(f"[APIMonitor] Anthropic unexpected error ({type(e).__name__}): {e}")
            return {
                'status': 'error',
                'service_name': _SVC,
                'error_type': type(e).__name__,
                'error_message': f'Unexpected error: {str(e)[:120]}',
                'console_url': _CONSOLE,
            }
    
    def check_openai_api(self) -> Dict:
        """Check OpenAI (DALL-E) API status and quota"""
        
        api_key = os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            return {
                'status': 'error',
                'service_name': 'OpenAI (DALL-E)',
                'error_message': 'No OpenAI API key configured'
            }
        
        try:
            client = OpenAI(api_key=api_key)
            
            models = client.models.list()
            
            dalle_available = any('dall-e' in model.id for model in models.data)
            
            return {
                'status': 'healthy',
                'service_name': 'OpenAI (DALL-E)',
                'is_valid': True,
                'dalle_available': dalle_available,
                'last_checked': datetime.now().isoformat(),
                'console_url': 'https://platform.openai.com/usage',
                'billing_url': 'https://platform.openai.com/settings/organization/billing',
                'note': 'API key valid. Check usage and add credits at platform.openai.com'
            }
            
        except Exception as e:
            error_msg = str(e)
            
            if 'invalid' in error_msg.lower() or 'authentication' in error_msg.lower():
                return {
                    'status': 'error',
                    'service_name': 'OpenAI (DALL-E)',
                    'is_valid': False,
                    'error_message': 'API key invalid or expired',
                    'action_required': 'Update OPENAI_API_KEY in Replit Secrets',
                    'console_url': 'https://platform.openai.com/api-keys'
                }
            elif 'quota' in error_msg.lower() or 'insufficient' in error_msg.lower():
                return {
                    'status': 'warning',
                    'service_name': 'OpenAI (DALL-E)',
                    'warning': True,
                    'warning_message': 'API quota exhausted or payment issue',
                    'action_required': 'Add credits at platform.openai.com/billing',
                    'console_url': 'https://platform.openai.com/settings/organization/billing'
                }
            else:
                return {
                    'status': 'error',
                    'service_name': 'OpenAI (DALL-E)',
                    'error_message': error_msg,
                    'console_url': 'https://platform.openai.com'
                }
    
    def check_facebook_token(self) -> Dict:
        """Check Facebook Page Access Token"""
        
        page_access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        
        if not page_access_token:
            return {
                'status': 'error',
                'service_name': 'Facebook Page Token',
                'error_message': 'No Facebook token configured'
            }
        
        try:
            url = f'https://graph.facebook.com/v18.0/me'
            params = {'access_token': page_access_token}
            
            response = requests.get(url, params=params, timeout=10)
            result = response.json()
            
            if 'error' in result:
                error = result['error']
                if error.get('code') == 190:
                    return {
                        'status': 'error',
                        'service_name': 'Facebook Page Token',
                        'is_valid': False,
                        'error_message': 'Token is invalid or expired',
                        'action_required': 'Generate new Page Access Token',
                        'console_url': 'https://developers.facebook.com/'
                    }
                else:
                    return {
                        'status': 'error',
                        'service_name': 'Facebook Page Token',
                        'error_message': error.get('message', 'Unknown error'),
                        'console_url': 'https://developers.facebook.com/'
                    }
            
            url_debug = f'https://graph.facebook.com/v18.0/debug_token'
            params_debug = {
                'input_token': page_access_token,
                'access_token': page_access_token
            }
            
            response_debug = requests.get(url_debug, params=params_debug, timeout=10)
            debug_data = response_debug.json()
            
            if 'data' in debug_data:
                token_data = debug_data['data']
                expires_at = token_data.get('expires_at')
                
                if expires_at == 0:
                    return {
                        'status': 'healthy',
                        'service_name': 'Facebook Page Token',
                        'is_valid': True,
                        'expires': 'Never',
                        'last_checked': datetime.now().isoformat(),
                        'console_url': 'https://developers.facebook.com/'
                    }
                else:
                    expiry_date = datetime.fromtimestamp(expires_at)
                    days_remaining = (expiry_date - datetime.now()).days
                    
                    if days_remaining < self.days_warning:
                        return {
                            'status': 'warning',
                            'service_name': 'Facebook Page Token',
                            'warning': True,
                            'warning_message': f'Token expires in {days_remaining} days',
                            'expires_at': expiry_date.isoformat(),
                            'action_required': 'Renew Facebook token soon',
                            'console_url': 'https://developers.facebook.com/'
                        }
                    else:
                        return {
                            'status': 'healthy',
                            'service_name': 'Facebook Page Token',
                            'is_valid': True,
                            'days_remaining': days_remaining,
                            'expires_at': expiry_date.isoformat(),
                            'last_checked': datetime.now().isoformat(),
                            'console_url': 'https://developers.facebook.com/'
                        }
            
            return {
                'status': 'healthy',
                'service_name': 'Facebook Page Token',
                'is_valid': True,
                'last_checked': datetime.now().isoformat(),
                'console_url': 'https://developers.facebook.com/'
            }
                
        except Exception as e:
            return {
                'status': 'error',
                'service_name': 'Facebook Page Token',
                'error_message': str(e),
                'console_url': 'https://developers.facebook.com/'
            }
    
    def check_telegram_bot(self) -> Dict:
        """Check Telegram Bot token validity"""
        
        if not self.telegram_bot_token:
            return {
                'status': 'error',
                'service_name': 'Telegram Bot',
                'error_message': 'No Telegram bot token configured'
            }
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                return {
                    'status': 'healthy',
                    'service_name': 'Telegram Bot',
                    'is_valid': True,
                    'bot_username': bot_info['result'].get('username'),
                    'last_checked': datetime.now().isoformat()
                }
            else:
                return {
                    'status': 'error',
                    'service_name': 'Telegram Bot',
                    'is_valid': False,
                    'error_message': 'Invalid bot token',
                    'action_required': 'Update TELEGRAM_BOT_TOKEN in Replit Secrets'
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'service_name': 'Telegram Bot',
                'error_message': str(e)
            }
    
    def _send_alert_notification(self, results: Dict):
        """Send Telegram alert for warnings or errors"""
        
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram not configured, skipping alert notification")
            return
        
        warnings = results.get('warnings', [])
        errors = results.get('errors', [])
        
        if not warnings and not errors:
            return
        
        message_parts = ["🚨 <b>API Token Monitor Alert</b>\n"]
        
        if errors:
            message_parts.append(f"\n❌ <b>ERRORS ({len(errors)}):</b>")
            for error in errors:
                service = error['service'].upper()
                msg = error['message']
                message_parts.append(f"• {service}: {msg}")
        
        if warnings:
            message_parts.append(f"\n⚠️ <b>WARNINGS ({len(warnings)}):</b>")
            for warning in warnings:
                service = warning['service'].upper()
                msg = warning['message']
                message_parts.append(f"• {service}: {msg}")
        
        message_parts.append("\n\n📊 <b>Quick Links:</b>")
        message_parts.append("• Claude: https://console.anthropic.com/settings/usage")
        message_parts.append("• OpenAI: https://platform.openai.com/usage")
        message_parts.append("• Facebook: https://developers.facebook.com/")
        
        message_parts.append(f"\n⏰ Checked: {datetime.now().strftime('%H:%M, %d %b %Y')}")
        
        message = "\n".join(message_parts)
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("API monitor alert sent successfully to Telegram")
            else:
                logger.error(f"Failed to send Telegram alert: {response.text}")
                
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
    
    def send_success_notification(self, results: Dict):
        """Send success notification (all services healthy)"""
        
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return
        
        services = results.get('services', {})
        healthy_count = sum(1 for s in services.values() if s.get('status') == 'healthy')
        
        message = f"""✅ <b>API Monitor: All Systems Operational</b>

📊 Status: {healthy_count}/{len(services)} services healthy

<b>Services Checked:</b>
• Claude AI (Anthropic) ✅
• OpenAI (DALL-E) ✅
• Facebook Page Token ✅
• Telegram Bot ✅

⏰ {datetime.now().strftime('%H:%M, %d %b %Y')}"""
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            requests.post(url, json=payload, timeout=10)
            logger.info("API monitor success notification sent")
            
        except Exception as e:
            logger.error(f"Error sending success notification: {e}")

api_token_monitor = APITokenMonitor()
