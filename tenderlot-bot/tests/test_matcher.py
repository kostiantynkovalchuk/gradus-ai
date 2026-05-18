"""
Tests for phone number normalization.

Covers E.164 conversion and edge cases for Ukrainian numbers.
"""

import pytest

from tenderlot_bot.services.matcher import normalize_phone


class TestNormalizePhone:
    # ── Valid inputs that should normalize to +380671234567 ────────────────────

    def test_already_e164(self) -> None:
        assert normalize_phone("+380671234567") == "+380671234567"

    def test_leading_zero(self) -> None:
        assert normalize_phone("0671234567") == "+380671234567"

    def test_country_code_no_plus(self) -> None:
        assert normalize_phone("380671234567") == "+380671234567"

    def test_spaces(self) -> None:
        assert normalize_phone("067 123 45 67") == "+380671234567"

    def test_dashes(self) -> None:
        assert normalize_phone("067-123-45-67") == "+380671234567"

    def test_parentheses(self) -> None:
        assert normalize_phone("(067) 123-45-67") == "+380671234567"

    def test_mixed_separators(self) -> None:
        assert normalize_phone("+38 (067) 123-45-67") == "+380671234567"

    def test_trailing_spaces(self) -> None:
        assert normalize_phone("  +380671234567  ") == "+380671234567"

    # ── Different valid Ukrainian numbers ──────────────────────────────────────

    def test_kyivstar(self) -> None:
        assert normalize_phone("+380671234567") == "+380671234567"

    def test_vodafone(self) -> None:
        assert normalize_phone("0501234567") == "+380501234567"

    def test_lifecell(self) -> None:
        assert normalize_phone("0931234567") == "+380931234567"

    # ── Mock test phone ────────────────────────────────────────────────────────
    # +380000000001 is a deliberately fake number used in seed_data.py for dev testing.
    # The phonenumbers library correctly rejects it as invalid — that is expected.
    # The seed_data matcher bypasses normalize_phone by storing E.164 directly in the DB.
    def test_mock_test_phone_is_invalid(self) -> None:
        assert normalize_phone("+380000000001") is None

    # ── International (non-Ukrainian) numbers — Bug 2 regression suite ────────
    # Telegram strips the leading + from Contact.phone_number, so all variants
    # without + must normalize to the same E.164 form as with +.

    def test_spanish_with_plus(self) -> None:
        assert normalize_phone("+34692480784") == "+34692480784"

    def test_spanish_stripped_plus(self) -> None:
        # Telegram sends Contact.phone_number as "34692480784" (no +)
        assert normalize_phone("34692480784") == "+34692480784"

    def test_spanish_double_zero_prefix(self) -> None:
        assert normalize_phone("0034692480784") == "+34692480784"

    def test_spanish_with_spaces(self) -> None:
        assert normalize_phone("+34 692 480 784") == "+34692480784"

    def test_spanish_with_dashes(self) -> None:
        assert normalize_phone("+34-692-480-784") == "+34692480784"

    # ── Invalid / unparseable inputs → None ───────────────────────────────────

    def test_empty_string(self) -> None:
        assert normalize_phone("") is None

    def test_too_short(self) -> None:
        assert normalize_phone("12345") is None

    def test_letters(self) -> None:
        assert normalize_phone("abc-def") is None

    def test_none_like_empty(self) -> None:
        # Empty string should return None
        assert normalize_phone("") is None
