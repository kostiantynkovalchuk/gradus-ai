"""
Single source of truth for Claude model identifiers.
Update here when migrating models — do not hardcode model strings elsewhere.
"""

# Client-facing — quality matters
SONNET = "claude-sonnet-4-6"

# Background tasks — cost-optimised
HAIKU = "claude-haiku-4-5-20251001"

# Vision (same as SONNET today; separated for future flexibility)
VISION = SONNET

# Reserved for high-intelligence workloads if needed
OPUS = "claude-opus-4-6"
