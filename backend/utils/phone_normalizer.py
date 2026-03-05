import re
import logging

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str | None:
    """
    Normalize any phone to 380XXXXXXXXX (12 digits).
    Returns None for invalid/non-normalizable numbers.

    Handles:
    - (095)810-00-72  → 380958100072
    - 067-631-33-99   → 380676313399
    - +380956900289   → 380956900289
    - 0671234567      → 380671234567
    - 380XXXXXXXXX    → 380XXXXXXXXX (passthrough)
    - +34692480784    → None (non-UA, handled by whitelist)
    - (380)987-82-53  → None (only 10 digits after strip, bad data)
    """
    if not phone or not isinstance(phone, str):
        return None

    digits = re.sub(r'\D', '', phone)

    if len(digits) == 10 and digits.startswith('0'):
        return '380' + digits[1:]
    elif len(digits) == 12 and digits.startswith('380'):
        return digits
    elif len(digits) == 13 and digits.startswith(('380', '0380')):
        return digits[-12:]
    elif len(digits) == 11 and digits.startswith('80'):
        return '3' + digits
    else:
        return None


def generate_format_variations(phone_normalized: str) -> list:
    if not phone_normalized or len(phone_normalized) != 12:
        return [phone_normalized] if phone_normalized else []

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
    if not phone_normalized or len(phone_normalized) != 12:
        return phone_normalized or ""

    digits = phone_normalized[3:]
    return f"+380 {digits[0:2]} {digits[2:5]} {digits[5:7]} {digits[7:9]}"
