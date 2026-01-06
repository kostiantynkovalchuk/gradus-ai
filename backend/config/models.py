"""
Claude Model Configuration

Channel-based model selection:
- Telegram (internal staff): Haiku 4.5 (~75% cheaper)
- Website (potential clients): Sonnet 4.5 (best Ukrainian quality)
- Content generation: Sonnet 4.5 (translation, images, categorization)
"""

# Chat models by source
CLAUDE_MODEL_TELEGRAM = "claude-haiku-4-5-20251001"    # Internal staff, cost-effective
CLAUDE_MODEL_WEBSITE = "claude-sonnet-4-5-20250929"   # Client-facing, best quality

# Content generation (always high quality)
CLAUDE_MODEL_CONTENT = "claude-sonnet-4-20250514"

# Legacy alias (for backward compatibility)
CLAUDE_MODEL_CHAT = CLAUDE_MODEL_TELEGRAM
