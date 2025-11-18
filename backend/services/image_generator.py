import os
from openai import OpenAI
from anthropic import Anthropic
from typing import Dict, Optional
import logging

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

CRITICAL: NO TEXT OR WORDS should appear in the image
- Do not include any letters, numbers, labels, or captions
- Use purely visual elements (charts, bottles, ingredients, settings)
- Let the imagery speak for itself without text overlays

Create a detailed DALL-E prompt (2-3 sentences) that will generate an appropriate text-free image.
Return ONLY the prompt text, nothing else."""

        try:
            message = self.claude_client.messages.create(
                model="claude-sonnet-4-20250514",
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
    
    def generate_image(self, prompt: str) -> Optional[str]:
        """
        Generate an image using DALL-E based on the provided prompt.
        Returns the URL of the generated image.
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
                return image_url
            else:
                logger.error("No image URL in response")
                return None
            
        except Exception as e:
            logger.error(f"DALL-E image generation error: {str(e)}")
            return None
    
    def generate_article_image(self, article_data: Dict) -> Dict[str, str]:
        """
        Complete pipeline: generate prompt + generate image
        
        Returns:
            Dict with 'prompt' and 'image_url'
        """
        dalle_prompt = self.generate_image_prompt(article_data)
        
        if not dalle_prompt:
            return {"prompt": "", "image_url": ""}
        
        image_url = self.generate_image(dalle_prompt)
        
        return {
            "prompt": dalle_prompt,
            "image_url": image_url or ""
        }

image_generator = ImageGenerator()
