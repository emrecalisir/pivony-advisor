"""Tests for Advisor chart spec builders."""

import importlib.util
import json
import sys
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "chart_specs.py"
    spec = importlib.util.spec_from_file_location("core.chart_specs", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core.chart_specs"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
charts_from_tool_result = mod.charts_from_tool_result


def test_trends_produces_line_charts():
    payload = json.dumps(
        {
            "volume_daily": [{"day": "2026-06-01", "count": 10}, {"day": "2026-06-02", "count": 12}],
            "sentiment_daily": [
                {"day": "2026-06-01", "positive": 8, "negative": 2},
                {"day": "2026-06-02", "positive": 7, "negative": 3},
            ],
        }
    )
    charts = charts_from_tool_result("get_trends", payload)
    assert len(charts) >= 2
    assert charts[0]["chart_type"] == "line"
    assert charts[0]["labels"] == ["2026-06-01", "2026-06-02"]


def test_topic_sentiment_stacked_bar():
    payload = json.dumps(
        {
            "topic_sentiment": [
                {
                    "topic_name": "Oda",
                    "count": 100,
                    "positive_percentage": 40,
                    "neutral_percentage": 20,
                    "negative_percentage": 40,
                }
            ]
        }
    )
    charts = charts_from_tool_result("get_topic_sentiment", payload)
    assert len(charts) == 1
    assert charts[0]["chart_type"] == "stacked_bar"
    assert charts[0]["labels"] == ["Oda"]


def test_skips_error_payload():
    assert charts_from_tool_result("get_trends", json.dumps({"error": "fail"})) == []
