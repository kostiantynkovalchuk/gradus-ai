import re
import logging

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    if not phone:
        raise ValueError("Phone number is empty")

    digits_only = re.sub(r'\D', '', phone)

    if digits_only.startswith('380'):
        normalized = digits_only
    elif digits_only.startswith('0') and len(digits_only) == 10:
        normalized = '380' + digits_only[1:]
    elif digits_only.startswith('80') and len(digits_only) == 11:
        normalized = '3' + digits_only
    else:
        normalized = '380' + digits_only

    if len(normalized) != 12:
        raise ValueError(f"Invalid phone: {phone} (expected 12 digits, got {len(normalized)})")

    if not normalized.startswith('380'):
        raise ValueError(f"Invalid phone: {phone} (must be Ukrainian +380)")

    logger.debug(f"Normalized: {phone} -> {normalized}")
    return normalized


def generate_format_variations(phone_normalized: str) -> list:
    if len(phone_normalized) != 12:
        raise ValueError("Phone must be normalized first (12 digits)")

    local_digits = phone_normalized[3:]

    variations = [
        phone_normalized,
        f"+{phone_normalized}",
        f"0{local_digits}",
        f"+380 {local_digits[0:2]} {local_digits[2:5]} {local_digits[5:7]} {local_digits[7:9]}",
        f"380 {local_digits[0:2]} {local_digits[2:5]} {local_digits[5:7]} {local_digits[7:9]}",
    ]

    logger.debug(f"Generated {len(variations)} format variations for {phone_normalized}")
    return variations


def format_for_display(phone_normalized: str) -> str:
    if len(phone_normalized) != 12:
        return phone_normalized

    digits = phone_normalized[3:]
    return f"+380 {digits[0:2]} {digits[2:5]} {digits[5:7]} {digits[7:9]}"
