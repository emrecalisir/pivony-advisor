"""Tests for loop_insights classification, traceability, and trends."""

from quality_loop.loop_insights import (
    annotate_qa_issues,
    build_issue_traceability,
    classify_issue,
    collect_blocked_backlog,
    collect_regression_scenarios,
)


def test_classify_issue_blocked_for_api_scope():
    issue = {
        "description": "pivony-api-dev scope dışı endpoint",
        "fix_hint": "api-dev repo",
        "category": "tool_usage",
    }
    assert classify_issue(issue) == "blocked"


def test_classify_issue_flaky_for_rate_limit():
    issue = {
        "description": "429 rate limit from vertex",
        "fix_hint": "retry",
        "category": "error_handling",
    }
    assert classify_issue(issue) == "flaky"


def test_annotate_qa_issues_adds_classification_counts():
    qa = {
        "issues": [
            {"description": "bug in handler", "category": "code"},
            {"description": "429 rate limit", "category": "error_handling"},
        ]
    }
    out = annotate_qa_issues(qa)
    assert out is not None
    assert out["issues"][0]["issue_class"] == "code"
    assert out["issues"][1]["issue_class"] == "flaky"
    assert out["issue_classification"]["code"] == 1
    assert out["issue_classification"]["flaky"] == 1


def test_build_issue_traceability_maps_commits():
    qa = {
        "issues": [
            {"description": "empty reply", "severity": "high"},
            {"description": "wrong tool", "severity": "medium"},
        ]
    }
    fixes = {
        "fixes_applied": [
            {
                "file": "agent_stream.py",
                "qa_issue_index": 0,
                "commit_hash": "abc1234",
            }
        ],
        "fixes_skipped": [
            {"qa_issue_index": 1, "reason": "out of scope"},
        ],
    }
    rows = build_issue_traceability(qa, fixes)
    assert len(rows) == 2
    assert rows[0]["status"] == "fixed"
    assert rows[0]["commit_hashes"] == ["abc1234"]
    assert rows[1]["status"] == "skipped"


def test_collect_regression_scenarios_empty_without_cycles(monkeypatch):
    monkeypatch.setattr(
        "quality_loop.cycle_store.list_completed_cycles",
        lambda: [],
    )
    assert collect_regression_scenarios() == []


def test_collect_blocked_backlog_empty_without_cycles(monkeypatch):
    monkeypatch.setattr(
        "quality_loop.cycle_store.list_completed_cycles",
        lambda: [],
    )
    assert collect_blocked_backlog() == []
