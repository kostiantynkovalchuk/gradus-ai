import os
from anthropic import Anthropic
from typing import Optional

class ClaudeService:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-5"
    
    async def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """
        Send a chat message to Claude and get a response.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt if system_prompt else "You are a helpful AI assistant.",
                messages=[{"role": "user", "content": message}]
            )
            
            text_block = next((block for block in response.content if hasattr(block, 'text')), None)
            if text_block and hasattr(text_block, 'text'):
                return text_block.text
            return ""
        except Exception as e:
            raise Exception(f"Claude API error: {str(e)}")
    
    async def translate_to_ukrainian(self, text: str) -> str:
        """
        Translate English text to Ukrainian using Claude.
        """
        system_prompt = """You are a professional translator specializing in English to Ukrainian translation. 
        Your task is to translate the given text accurately while maintaining the original tone and meaning.
        Focus on alcohol industry terminology and marketing language.
        Return ONLY the translated text, nothing else."""
        
        user_message = f"Translate the following English text to Ukrainian:\n\n{text}"
        
        try:
            translation = await self.chat(user_message, system_prompt)
            return translation.strip()
        except Exception as e:
            raise Exception(f"Translation error: {str(e)}")
    
    async def generate_image_prompt(self, article_text: str, title: str) -> str:
        """
        Generate a DALL-E image prompt based on article content.
        """
        system_prompt = """You are an expert at creating detailed image generation prompts for DALL-E.
        Create a visual, descriptive prompt for an image that would accompany an article about alcohol/spirits.
        The prompt should be professional, eye-catching, and suitable for social media.
        Return ONLY the prompt, nothing else."""
        
        user_message = f"Article title: {title}\n\nArticle excerpt: {article_text[:500]}\n\nCreate a DALL-E prompt:"
        
        try:
            prompt = await self.chat(user_message, system_prompt)
            return prompt.strip()
        except Exception as e:
            raise Exception(f"Image prompt generation error: {str(e)}")

claude_service = ClaudeService()
