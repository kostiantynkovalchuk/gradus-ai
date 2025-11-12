import os
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set - image generation will not work")
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key)
    
    async def generate_image(self, prompt: str) -> str:
        """
        Generate an image using DALL-E based on the provided prompt.
        Returns the URL of the generated image.
        """
        if not self.client:
            logger.error("OpenAI client not initialized - missing API key")
            return "https://placehold.co/1024x1024?text=Image+Generation+Unavailable"
        
        try:
            response = self.client.images.generate(
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
                return "https://placehold.co/1024x1024?text=Image+Generation+Failed"
            
        except Exception as e:
            logger.error(f"DALL-E image generation error: {str(e)}")
            return "https://placehold.co/1024x1024?text=Image+Generation+Failed"

image_generator = ImageGenerator()
