"""Tests for Sonic Prospect multilingual prompt rules."""

from prospect.languages import (
    augment_prospect_system_prompt,
    build_language_instruction,
    normalize_page_locale,
)


def test_normalize_page_locale_unknown_defaults_en():
    assert normalize_page_locale("xx") == "en"
    assert normalize_page_locale("it") == "it"


def test_language_instruction_never_blocks_unlisted_language():
    text = build_language_instruction()
    assert "never say the language is unsupported" in text.lower()


def test_augment_includes_knowledge_gap_and_commercial():
    out = augment_prospect_system_prompt(
        "", page_locale="de", conversation_locale="en"
    )
    assert "KNOWLEDGE GAP RULE:" in out
    assert "PIVONY / SONIC PROSPECT COMMERCIAL" in out
    assert "$9" in out
    assert "conversation language: en" in out.lower()
    assert "Preferred response language" not in out
    assert "do not say plans depend on use case" in out.lower()
