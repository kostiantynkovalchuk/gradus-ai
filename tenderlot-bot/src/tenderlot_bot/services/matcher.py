"""
Phone number normalization and tenderlot user matching.

All phones are stored and compared in E.164 format: +XXXXXXXXXXX

Telegram's Contact.phone_number often strips the leading '+', so we handle:
  - Numbers already in E.164:    +34692480784  → +34692480784
  - Stripped '+':                 34692480784   → +34692480784
  - Double-zero international:   0034692480784 → +34692480784
  - With separators:             +34 692 480 784 → +34692480784
  - Ukrainian local (0xx):       0671234567    → +380671234567
  - Ukrainian without +380:      380671234567  → +380671234567
"""

import logging
import re

import phonenumbers
from phonenumbers import NumberParseException

logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str | None:
    """
    Normalize any phone input to E.164 format.

    Returns None if the number is unparseable or invalid.
    """
    if not raw:
        return None

    # Strip all whitespace, dashes, dots, parentheses
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", raw.strip())

    if not cleaned:
        return None

    # Normalize to E.164 format before handing to phonenumbers
    if cleaned.startswith("+"):
        # Already has country code prefix — pass through as-is
        pass
    elif cleaned.startswith("00"):
        # Double-zero international prefix → +
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("380"):
        # Ukrainian number without +
        cleaned = "+" + cleaned
    elif cleaned.startswith("0"):
        # Ukrainian local format: 0XX XXXXXXX → +380XXXXXXXXX
        cleaned = "+38" + cleaned
    else:
        # Bare international number (Telegram strips + from Contact.phone_number)
        cleaned = "+" + cleaned

    try:
        # Parse with no default region — we've already made the number international
        parsed = phonenumbers.parse(cleaned, None)
    except NumberParseException:
        logger.debug("[matcher] Failed to parse phone: %r → %r", raw, cleaned)
        return None

    if not phonenumbers.is_valid_number(parsed):
        logger.debug("[matcher] Invalid phone number: %r → %r", raw, cleaned)
        return None

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
