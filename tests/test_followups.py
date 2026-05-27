"""Tests for contextual follow-up suggestions."""

import importlib.util
import sys
from pathlib import Path


def _load_followups():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "followups.py"
    name = "_followups_test"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.generate_followups


generate_followups = _load_followups()


def test_dashboard_question_suggests_integrations():
    followups = generate_followups(
        "Dashboard nasıl oluşturabilirim?",
        "New Dashboard wizard ile /console/myDashboards üzerinden oluşturabilirsiniz.",
    )
    assert len(followups) == 3
    assert any("Zendesk" in item for item in followups)


def test_external_data_question_suggests_competitor_analysis():
    followups = generate_followups(
        "Dış veriyi nasıl analiz ederim?",
        "Market Intelligence ile public dashboard oluşturun.",
    )
    assert any("Competitor" in item or "rakip" in item.lower() for item in followups)


def test_refusal_returns_default_followups():
    followups = generate_followups(
        "Gizli bir şey",
        "Bu bilgiye sahip değilim.",
    )
    assert followups == [
        "Dashboard nasıl oluşturabilirim?",
        "Dış veriyi nasıl analiz ederim?",
        "Raporları nereden indirebilirim?",
    ]


def test_dedupes_question_from_followups():
    followups = generate_followups(
        "Zendesk entegrasyonu nasıl yapılır?",
        "Settings > Integrations üzerinden OAuth ile bağlayın.",
    )
    assert all("Zendesk entegrasyonu nasıl yapılır?" not in item for item in followups)
