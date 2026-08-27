"""Tests for Sonic Prospect multilingual prompt rules."""

from prospect.languages import (
    augment_prospect_system_prompt,
    build_language_instruction,
    normalize_page_locale,
)


def test_normalize_page_locale_unknown_defaults_en():
    assert normalize_page_locale("it") == "en"


def test_language_instruction_never_blocks_unlisted_language():
    text = build_language_instruction()
    assert "never say the language is unsupported" in text.lower()


def test_augment_includes_knowledge_gap_rule():
    out = augment_prospect_system_prompt("", page_locale="de")
    assert "KNOWLEDGE GAP RULE:" in out
    assert "Preferred response language" not in out
