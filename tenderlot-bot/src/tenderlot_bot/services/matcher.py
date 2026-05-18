"""
Phone number normalization and tenderlot user matching.

All phones are stored and compared in E.164 format: +380XXXXXXXXX
"""

import logging
import re

import phonenumbers
from phonenumbers import NumberParseException

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "UA"


def normalize_phone(raw: str) -> str | None:
    """
    Normalize any Ukrainian phone input to E.164 format.

    Handles formats:
      0671234567       → +380671234567
      +380671234567    → +380671234567
      380671234567     → +380671234567
      (067) 123-45-67  → +380671234567
      067 123 45 67    → +380671234567

    Returns None if the number is unparseable or invalid.
    """
    if not raw:
        return None

    cleaned = re.sub(r"[\s\-\(\)\.]+", "", raw.strip())

    # Prepend + if starts with digits only
    if cleaned.startswith("380") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    elif cleaned.startswith("0") and not cleaned.startswith("+"):
        cleaned = "+38" + cleaned

    try:
        parsed = phonenumbers.parse(cleaned, _DEFAULT_REGION)
    except NumberParseException:
        logger.debug("[matcher] Failed to parse phone: %r", raw)
        return None

    if not phonenumbers.is_valid_number(parsed):
        logger.debug("[matcher] Invalid phone number: %r", raw)
        return None

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
