import os
import requests
import hashlib
from pathlib import Path
from openai import OpenAI
from anthropic import Anthropic
from typing import Dict, Optional
import logging
from config.models import CLAUDE_MODEL_CONTENT

logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        openai_key = os.getenv("OPENAI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not openai_key:
            logger.warning("OPENAI_API_KEY not set - image generation will not work")
            self.openai_client = None
        else:
            self.openai_client = OpenAI(api_key=openai_key)
        
        if not anthropic_key:
            logger.warning("ANTHROPIC_API_KEY not set - prompt generation will not work")
            self.claude_client = None
        else:
            self.claude_client = Anthropic(api_key=anthropic_key)
        
        # Set up permanent image storage directory
        self.image_storage_dir = Path("attached_assets/generated_images")
        self.image_storage_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_image_prompt(self, article_data: Dict) -> str:
        """
        Use Claude to generate a professional DALL-E prompt based on article content
        """
        if not self.claude_client:
            logger.error("Claude client not initialized")
            return ""
        
        title = article_data.get('title', '')
        content = article_data.get('content', '')[:1000]
        
        prompt = f"""Based on this alcohol industry article, create a professional DALL-E image prompt for a social media post.

Article Title: {title}
Article Content: {content}

Requirements for the image prompt:
- Professional, premium alcohol industry aesthetic
- Suitable for Facebook/LinkedIn business posts
- Modern, clean, minimalist design
- Relevant to the article topic
- Brand-safe (no specific brand logos unless mentioned in article)
- Color scheme: premium (blues, golds, silvers, or warm earth tones)
- Style: photorealistic or professional infographic

CRITICAL COMPOSITION GUIDELINES (AI cannot generate readable text):
- If bottles appear: use "soft focus", "backlit", "bokeh effect", "silhouetted", or "distant shot"
- NEVER use: "close-up of label", "text on bottle", "readable brand name", "label details"
- Prefer: atmospheric scenes, artistic lighting that naturally obscures labels
- Focus on: mood, setting, professional context rather than product details
- Show bottles from behind, at angles, or with dramatic lighting that hides text
- Great alternatives: bar interiors, cocktail preparation, ingredient still life, industry settings

HUMAN FIGURE GUIDELINES (AI struggles with faces, hands, proportions):
- Minimize or eliminate human figures entirely
- If humans must appear: show only hands performing actions, or use silhouettes/back-turned figures
- Keep people distant and out of focus as environmental context only
- NEVER show close-up faces, detailed hand positions, or full body portraits
- Prefer: architectural shots, product focus, detail photography, empty elegant spaces
- Product-focused imagery is more relevant for beverage industry professionals

ABSOLUTE RULE: NO TEXT OR WORDS in the image
- No letters, numbers, labels, captions, or signage
- Use purely visual storytelling without any text elements

Create a detailed DALL-E prompt (2-3 sentences) that will generate an appropriate text-free image.
Return ONLY the prompt text, nothing else."""

        try:
            message = self.claude_client.messages.create(
                model=CLAUDE_MODEL_CONTENT,
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            dalle_prompt = message.content[0].text.strip()
            
            # Add explicit "no text" instruction to DALL-E prompt
            dalle_prompt += " No text, labels, or words in the image."
            
            logger.info(f"Generated DALL-E prompt: {dalle_prompt[:100]}...")
            return dalle_prompt
            
        except Exception as e:
            logger.error(f"Failed to generate image prompt: {e}")
            return ""
    
    def download_and_save_image(self, image_url: str) -> Optional[Dict[str, any]]:
        """
        Download image from DALL-E temporary URL and save permanently.
        Returns dict with local_path and image_data (binary).
        """
        try:
            # Download the image
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            image_data = response.content
            
            # Generate unique filename using hash of URL
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
            filename = f"dalle_{url_hash}.png"
            filepath = self.image_storage_dir / filename
            
            # Save to filesystem (for local dev/Replit)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            # Return ABSOLUTE path and binary data
            absolute_path = str(filepath.absolute())
            logger.info(f"Image saved permanently to: {absolute_path} ({len(image_data)} bytes)")
            
            return {
                'local_path': absolute_path,
                'image_data': image_data  # Binary data for database storage
            }
            
        except Exception as e:
            logger.error(f"Failed to download and save image: {e}")
            return None
    
    def generate_image(self, prompt: str) -> Optional[Dict]:
        """
        Generate an image using DALL-E based on the provided prompt.
        Returns dict with temporary URL, local path, and binary image data.
        """
        if not self.openai_client:
            logger.error("OpenAI client not initialized - missing API key")
            return None
        
        if not prompt:
            logger.error("Empty prompt provided")
            return None
        
        try:
            response = self.openai_client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            
            if response.data and len(response.data) > 0 and response.data[0].url:
                image_url = response.data[0].url
                logger.info(f"Image generated successfully: {image_url}")
                
                # Download and save immediately to prevent expiration issues
                save_result = self.download_and_save_image(image_url)
                
                if save_result:
                    return {
                        'url': image_url,  # Temporary DALL-E URL (expires in 1-2 hours)
                        'local_path': save_result['local_path'],  # Local file path
                        'image_data': save_result['image_data']  # Binary data for DB storage
                    }
                else:
                    return {
                        'url': image_url,
                        'local_path': None,
                        'image_data': None
                    }
            else:
                logger.error("No image URL in response")
                return None
            
        except Exception as e:
            logger.error(f"DALL-E image generation error: {str(e)}")
            return None
    
    def generate_article_image(self, article_data: Dict) -> Dict:
        """
        Complete pipeline: generate prompt + generate image
        
        Returns:
            Dict with 'prompt', 'image_url', 'local_path', and 'image_data' (binary)
        """
        dalle_prompt = self.generate_image_prompt(article_data)
        
        if not dalle_prompt:
            return {"prompt": "", "image_url": "", "local_path": "", "image_data": None}
        
        image_result = self.generate_image(dalle_prompt)
        
        if not image_result:
            return {"prompt": dalle_prompt, "image_url": "", "local_path": "", "image_data": None}
        
        return {
            "prompt": dalle_prompt,
            "image_url": image_result.get('url', ''),
            "local_path": image_result.get('local_path', ''),
            "image_data": image_result.get('image_data')  # Binary data for DB storage
        }

image_generator = ImageGenerator()
