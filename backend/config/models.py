"""
Claude Model Configuration

Channel-based model selection:
- Telegram (internal staff): Haiku 4.5 (~75% cheaper)
- Website (potential clients): Sonnet 4.6 (best Ukrainian quality)
- Content generation: Sonnet 4.6 (translation, images, categorization)

Alex Gradus model split:
- User-facing chat (all paid tiers): Sonnet for consistent quality
- Background extraction/summarization: Haiku for cost efficiency

Model identifiers are the single source of truth in services/ai_models.py.
"""
from services.ai_models import SONNET, HAIKU

# Chat models by source
CLAUDE_MODEL_TELEGRAM = HAIKU    # Internal staff, cost-effective
CLAUDE_MODEL_WEBSITE = SONNET    # Client-facing, best quality

# Content generation (always high quality)
CLAUDE_MODEL_CONTENT = SONNET

# Legacy alias (for backward compatibility)
CLAUDE_MODEL_CHAT = CLAUDE_MODEL_TELEGRAM

# Alex Gradus model split
ALEX_CHAT_MODEL = SONNET        # All user-facing Alex responses
ALEX_EXTRACTION_MODEL = HAIKU   # Background profile extraction & summarization
