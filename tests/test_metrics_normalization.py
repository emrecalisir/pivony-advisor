"""Tests for NPS metrics normalization (no false zero scores)."""

import importlib.util
import sys
from pathlib import Path


def _load_normalize():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "metrics_normalize.py"
    spec = importlib.util.spec_from_file_location("core.metrics_normalize", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_normalize()
normalize_metrics_response = _mod.normalize_metrics_response
normalize_topic_intent_response = _mod.normalize_topic_intent_response
normalize_topic_sentiment_response = _mod.normalize_topic_sentiment_response
normalize_root_causes_response = _mod.normalize_root_causes_response
normalize_key_drivers_response = _mod.normalize_key_drivers_response


def test_nps_zero_with_no_reviews_becomes_unavailable():
    out = normalize_metrics_response(
        {"dashboard_id": 6208, "review_count": 0, "nps": 0, "dashboard_count": 1}
    )
    assert out["nps"] is None
    assert out["nps_status"] == "no_reviews_in_period"
    assert out["nps_available"] is False


def test_org_wide_scope_requires_single_dashboard():
    out = normalize_metrics_response(
        {"dashboard_id": None, "review_count": 120, "nps": None, "dashboard_count": 15}
    )
    assert out["nps_status"] == "requires_single_dashboard"
    assert out["nps_available"] is False


def test_real_nps_preserved():
    out = normalize_metrics_response(
        {"dashboard_id": 6208, "review_count": 42, "nps": 38.5, "dashboard_count": 1}
    )
    assert out["nps"] == 38.5
    assert out["nps_status"] == "ok"
    assert out["nps_available"] is True


def test_nps_disabled_pipeline_not_reported_as_zero():
    out = normalize_metrics_response(
        {
            "dashboard_id": 6208,
            "review_count": 74,
            "avg_rating": 3.65,
            "nps": 0,
            "nps_enabled": False,
            "nps_status": "ok",
            "dashboard_count": 1,
        }
    )
    assert out["nps"] is None
    assert out["nps_status"] == "unavailable"
    assert out["nps_available"] is False
    assert "yapılandırılmamış" in out["nps_guidance"]


def test_topic_intent_no_complaint_topics_flags_guidance():
    out = normalize_topic_intent_response(
        {
            "topics": [
                {"topic": "Acente", "complaint_pct": 0, "intent_pcts": {"complaint": 0}},
            ]
        }
    )
    assert out["intent_status"] == "no_complaint_intent_topics"
    assert "intent_guidance" in out


def test_topic_sentiment_flags_all_mixed_topics():
    out = normalize_topic_sentiment_response(
        {
            "topic_sentiment": [
                {
                    "topic": "Hasar",
                    "positive_pct": 0,
                    "neutral_pct": 0,
                    "negative_pct": 0,
                    "mixed_pct": 100,
                }
            ]
        }
    )
    assert out["sentiment_status"] == "suspiciously_100_percent_mixed_topics"
    assert "Hasar" in out["sentiment_guidance"]


def test_root_causes_not_generated_adds_synthesis_guidance():
    out = normalize_root_causes_response({"status": "not_generated"})
    assert "synthesis_guidance" in out


def test_key_drivers_no_config_adds_synthesis_guidance():
    out = normalize_key_drivers_response({"status": "no_config"})
    assert "synthesis_guidance" in out
