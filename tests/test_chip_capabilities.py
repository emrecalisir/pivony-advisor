"""Tests for chip capability guardrails."""

import importlib.util
import sys
from pathlib import Path


def _load_chip_capabilities():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "chip_capabilities.py"
    spec = importlib.util.spec_from_file_location("core.chip_capabilities", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core.chip_capabilities"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_chip_capabilities()


def test_blocks_integration_howto():
    assert mod.is_out_of_scope_chip("Zendesk entegrasyonu nasıl yapılır?")
    assert mod.is_out_of_scope_chip("Dashboard nasıl oluşturabilirim?")
    assert mod.is_out_of_scope_chip("Raporları nereden indirebilirim?")


def test_allows_analytics_questions():
    assert not mod.is_out_of_scope_chip("Bu dönemde en çok şikayet edilen konular neler?")
    assert not mod.is_out_of_scope_chip("Konu bazında şikayet oranları neler?")
    assert not mod.is_out_of_scope_chip("NPS son dönemde nasıl bir trend izliyor?")


def test_sanitize_replaces_blocked_with_defaults():
    cleaned = mod.sanitize_chip_questions(
        [
            "Zendesk entegrasyonu nasıl yapılır?",
            "Dashboard nasıl oluşturabilirim?",
        ],
        limit=3,
    )
    assert len(cleaned) == 3
    assert all(not mod.is_out_of_scope_chip(item) for item in cleaned)
