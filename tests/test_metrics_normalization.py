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
