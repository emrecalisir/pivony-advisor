"""Tests for contextual follow-up suggestions."""

import importlib.util
import sys
from pathlib import Path


def _load_followups():
    root = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(root))

    chip_path = root / "core" / "chip_capabilities.py"
    chip_spec = importlib.util.spec_from_file_location("core.chip_capabilities", chip_path)
    chip_mod = importlib.util.module_from_spec(chip_spec)
    sys.modules["core.chip_capabilities"] = chip_mod
    chip_spec.loader.exec_module(chip_mod)

    path = root / "core" / "followups.py"
    spec = importlib.util.spec_from_file_location("core.followups", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core.followups"] = mod
    spec.loader.exec_module(mod)
    return mod.generate_followups


generate_followups = _load_followups()
DEFAULTS = [
    "Bu dönemde en çok şikayet edilen konular neler?",
    "Genel müşteri memnuniyeti (duyarlılık) ne durumda?",
    "Şikayetlerin temel nedenleri neler?",
]


def test_dashboard_howto_gets_data_chips_not_integrations():
    followups = generate_followups(
        "Dashboard nasıl oluşturabilirim?",
        "New Dashboard wizard ile /console/myDashboards üzerinden oluşturabilirsiniz.",
    )
    assert len(followups) == 3
    assert all("Zendesk" not in item for item in followups)
    assert all("entegrasyon" not in item.lower() for item in followups)
    assert any("şikayet" in item.lower() or "duyarlılık" in item.lower() for item in followups)


def test_external_data_question_gets_analytics_chips():
    followups = generate_followups(
        "Dış veriyi nasıl analiz ederim?",
        "Market Intelligence ile public dashboard oluşturun.",
    )
    assert len(followups) == 3
    assert all("Competitor" not in item for item in followups)
    assert all("rakip analiz" not in item.lower() for item in followups)


def test_refusal_returns_default_followups():
    followups = generate_followups(
        "Gizli bir şey",
        "Bu bilgiye sahip değilim.",
    )
    assert followups == DEFAULTS


def test_dedupes_question_from_followups():
    followups = generate_followups(
        "Zendesk entegrasyonu nasıl yapılır?",
        "Settings > Integrations üzerinden OAuth ile bağlayın.",
    )
    assert all("Zendesk entegrasyonu nasıl yapılır?" not in item for item in followups)
    assert all("Zendesk" not in item for item in followups)


def test_sentiment_question_suggests_mcp_aligned_followups():
    followups = generate_followups(
        "Genel duyarlılık nasıl?",
        "Son 7 günde pozitif duyarlılık %61.",
    )
    assert len(followups) == 3
    assert any("şikayet" in item.lower() or "nps" in item.lower() for item in followups)
