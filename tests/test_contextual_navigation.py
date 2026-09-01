"""Tests for Vertex AI contextual navigation (fallback path)."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_file_module(relative_path: str, module_name: str):
    path = Path(__file__).resolve().parents[1] / "src" / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_contextual_navigation():
    core_pkg = types.ModuleType("core")
    sys.modules.setdefault("core", core_pkg)

    chip_mod = _load_file_module("core/chip_capabilities.py", "_chip_caps_for_nav")
    sys.modules["core.chip_capabilities"] = chip_mod
    core_pkg.chip_capabilities = chip_mod

    followups_mod = _load_file_module("core/followups.py", "_followups_for_nav")
    sys.modules["core.followups"] = followups_mod
    core_pkg.followups = followups_mod

    guidance_mod = _load_file_module("core/guidance.py", "_guidance_for_nav")
    sys.modules["core.guidance"] = guidance_mod
    core_pkg.guidance = guidance_mod

    llm_mod = _load_file_module("core/llm_resilience.py", "_llm_resilience_for_nav")
    sys.modules["core.llm_resilience"] = llm_mod
    core_pkg.llm_resilience = llm_mod

    return _load_file_module(
        "core/contextual_navigation.py",
        "_contextual_navigation_test",
    )


mod = _load_contextual_navigation()
generate_contextual_navigation = mod.generate_contextual_navigation
should_offer_navigation_chips = mod.should_offer_navigation_chips
maybe_generate_contextual_navigation = mod.maybe_generate_contextual_navigation


def test_refusal_uses_rule_based_fallback():
    followups, guidance = generate_contextual_navigation(
        "Gizli bir şey",
        "Bu bilgiye sahip değilim.",
        use_vertex=False,
    )
    assert len(followups) == 3
    assert "İstersen bir sonraki adımda" in guidance


def test_vertex_disabled_uses_rule_based_fallback():
    followups, guidance = generate_contextual_navigation(
        "Dashboard nasıl oluşturabilirim?",
        "New Dashboard wizard ile oluşturabilirsiniz.",
        use_vertex=False,
    )
    assert len(followups) == 3
    assert all("Zendesk" not in item for item in followups)
    assert guidance


def test_vertex_failure_falls_back():
    broken_llm = MagicMock()
    broken_llm.with_structured_output.side_effect = RuntimeError("vertex unavailable")

    followups, guidance = generate_contextual_navigation(
        "Dış veriyi nasıl analiz ederim?",
        "Market Intelligence ile public dashboard oluşturun.",
        llm=broken_llm,
        use_vertex=True,
    )
    assert len(followups) == 3
    assert guidance


def test_should_offer_skips_kpi_flow():
    assert not should_offer_navigation_chips(
        "kpi oluşturabilir misin",
        "Hangi dashboard için KPI oluşturmak istersiniz?",
    )


def test_should_offer_skips_confirmation():
    assert not should_offer_navigation_chips(
        "evet",
        "Survey dashboard, Voyage Torba ve Yüzme doğru mu — onaylıyor musunuz?",
    )


def test_should_offer_skips_single_dashboard_prompt():
    assert not should_offer_navigation_chips(
        "kaç yorum var",
        "Hangi dashboard'u inceleyelim?",
    )


def test_should_offer_allows_substantive_data_answer():
    assert should_offer_navigation_chips(
        "nps nedir",
        "Bu dönemde NPS 42. Pozitif duyarlılık %65.",
    )


def test_maybe_generate_skips_kpi_without_chips():
    followups, guidance = maybe_generate_contextual_navigation(
        "kpi oluştur",
        "Hangi dashboard için KPI oluşturalım?",
        use_vertex=False,
    )
    assert followups == []
    assert guidance == ""
