"""Tests for pivot key alias normalization and semantic-search blocking."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_pivot_resolve(fetch_pivots=None):
    fake_platform = types.ModuleType("core.pivony_platform")
    fake_platform.fetch_pivots = fetch_pivots or MagicMock(return_value=None)
    sys.modules["core.pivony_platform"] = fake_platform
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "pivot_resolve.py"
    spec = importlib.util.spec_from_file_location("core.pivot_resolve", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core.pivot_resolve"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_normalize_pivot_key_vendor_alias():
    mod = _load_pivot_resolve()
    assert mod.normalize_pivot_key("vendor_name") == "vendorName"
    assert mod.normalize_pivot_key("vendorName") == "vendorName"
    assert mod.normalize_pivot_key("Marka", ["vendorName", "channel"]) == "Marka"


def test_looks_like_pivot_scoped_search():
    mod = _load_pivot_resolve()
    assert mod.looks_like_pivot_scoped_search("Voyage Torba oda şikayetleri")
    assert mod.looks_like_pivot_scoped_search("pivot_key vendor_name voyage torba")
    assert not mod.looks_like_pivot_scoped_search("genel memnuniyet nasıl")


def test_semantic_search_redirect_json():
    mod = _load_pivot_resolve()
    payload = json.loads(mod.semantic_search_pivot_redirect())
    assert payload["error"] == "use_pivot_tools"
    assert "list_reviews" in payload["instruction"]


def test_resolve_pivot_scope_fuzzy_match():
    mock_fetch = MagicMock(
        return_value={
            "pivots": {"vendorName": ["Other Hotel"]},
            "matches": [
                {"pivot_key": "vendorName", "pivot_value": "Voyage Torba", "count": 12}
            ],
        }
    )
    mod = _load_pivot_resolve(fetch_pivots=mock_fetch)
    key, value, meta = mod.resolve_pivot_scope("u1", 6208, "vendor_name", "voyage torba")
    assert key == "vendorName"
    assert value == "Voyage Torba"
    assert meta["pivot_resolved"]["to"]["pivot_value"] == "Voyage Torba"


def test_apply_pivot_to_tool_args():
    mock_fetch = MagicMock(
        return_value={
            "pivots": {"vendorName": []},
            "matches": [
                {"pivot_key": "vendorName", "pivot_value": "Voyage Torba", "count": 5}
            ],
        }
    )
    mod = _load_pivot_resolve(fetch_pivots=mock_fetch)
    out = mod.apply_pivot_to_tool_args(
        "list_reviews",
        {"dashboard_id": 6208, "pivot_key": "vendor_name", "pivot_value": "torba"},
        user_id="u1",
        dashboard_id=6208,
    )
    assert out["pivot_key"] == "vendorName"
    assert out["pivot_value"] == "Voyage Torba"
