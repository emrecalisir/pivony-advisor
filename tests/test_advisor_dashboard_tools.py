"""Regression tests for dashboard-scoped advisor tool guidance."""

from pathlib import Path

_PROMPTS_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "core" / "prompts.py"
)
AGENT_TOOL_GUIDANCE = _PROMPTS_PATH.read_text(encoding="utf-8")


def test_prompts_route_topic_complaint_to_topic_intent_tool():
    assert "get_topic_intent_distribution" in AGENT_TOOL_GUIDANCE
    assert "complaint_pct" in AGENT_TOOL_GUIDANCE
    assert "topiclerin şikayet oranı" in AGENT_TOOL_GUIDANCE
    assert "Do NOT use `get_distribution(kind=intent)`" in AGENT_TOOL_GUIDANCE


def test_prompts_keep_positive_sentiment_rule():
    assert "positive_sentiment_score" in AGENT_TOOL_GUIDANCE
    assert "pozitif duyarlılık skoru" in AGENT_TOOL_GUIDANCE


def test_prompts_document_ratings_daily_in_trends():
    assert "ratings_daily" in AGENT_TOOL_GUIDANCE


def test_prompts_document_distribution_kinds():
    for kind in ("rating", "fraud", "praise_intent"):
        assert kind in AGENT_TOOL_GUIDANCE


def test_prompts_document_topic_daily_tools():
    for tool in (
        "get_topic_sentiment_daily",
        "get_topic_participation_daily",
        "get_topic_trends_view",
        "get_review_statistics",
    ):
        assert tool in AGENT_TOOL_GUIDANCE


def test_prompts_no_longer_claim_daily_sentiment_unavailable():
    assert "not yet available" not in AGENT_TOOL_GUIDANCE
    assert "get_topic_sentiment_daily" in AGENT_TOOL_GUIDANCE
