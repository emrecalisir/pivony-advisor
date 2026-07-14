"""Tests for established analytics scope inference."""

import importlib.util
import sys
from pathlib import Path


def _load_analytics_scope():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "analytics_scope.py"
    name = "_analytics_scope_test"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_analytics_scope()
assistant_text_has_substantive_data = _mod.assistant_text_has_substantive_data
infer_established_analytics_scope = _mod.infer_established_analytics_scope
scope_prompt_block = _mod.scope_prompt_block


def test_substantive_data_detection():
    assert assistant_text_has_substantive_data("Pozitif: %61")
    assert not assistant_text_has_substantive_data("Merhaba!")


def test_inherit_org_wide_from_prior_answer():
    turns = [
        ("user", "Genel misafir memnuniyeti nasıl?"),
        (
            "assistant",
            "Son 7 güne ait verilere göre pozitif duyarlılık %61. Toplam 21.841 yorum.",
        ),
        ("user", "NPS veya ortalama puanımız nedir?"),
    ]
    scope = infer_established_analytics_scope(turns, None)
    assert scope is not None
    assert scope.org_wide is True
    assert scope.days == 7


def test_page_context_dashboard_overrides_inference():
    turns = [
        ("user", "NPS?"),
    ]
    scope = infer_established_analytics_scope(
        turns, {"analytics_scope": {"dashboard_id": 6198, "org_wide": False}}
    )
    assert scope is not None
    assert scope.dashboard_id == 6198


def test_page_dashboard_id_blocks_org_wide_inference():
    turns = [
        ("user", "negatiflik trendi"),
        ("assistant", "Son 7 günde negatif oran %12."),
        ("user", "grafiği tekrar oluştur"),
    ]
    scope = infer_established_analytics_scope(
        turns,
        {
            "dashboard_id": 6208,
            "last_dashboard_selection": {"id": 6208, "name": "SURVEY"},
        },
    )
    assert scope is not None
    assert scope.dashboard_id == 6208
    assert scope.org_wide is False


def test_org_wide_analytics_scope_defers_to_last_dashboard_selection():
    scope = infer_established_analytics_scope(
        [
            ("user", "memnuniyet"),
            ("assistant", "Son 7 güne ait verilere göre %61 pozitif."),
            ("user", "NPS?"),
        ],
        {
            "analytics_scope": {"org_wide": True, "days": 7},
            "last_dashboard_selection": {"id": 4077, "name": "Prima"},
        },
    )
    assert scope is not None
    assert scope.dashboard_id == 4077
    assert scope.org_wide is False


def test_scope_prompt_org_wide():
    block = scope_prompt_block(
        infer_established_analytics_scope(
            [
                ("user", "memnuniyet"),
                ("assistant", "Son 7 güne ait verilere göre %61 pozitif."),
                ("user", "NPS?"),
            ],
            None,
        )
    )
    assert "org_wide=true" in block
    assert "list_dashboards" in block


def test_dashboard_id_zero_placeholder_ignored():
    scope = infer_established_analytics_scope(
        [("user", "NPS?")],
        {
            "dashboard_selection": {"id": 0, "name": "Dashboard 0"},
            "last_dashboard_selection": {"id": 6208, "name": "SURVEY"},
        },
    )
    assert scope is not None
    assert scope.dashboard_id == 6208
    assert scope.org_wide is False
