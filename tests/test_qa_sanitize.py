"""Tests for QA report sanitization."""

from __future__ import annotations

from quality_loop.qa_sanitize import sanitize_qa_report


def test_drops_out_of_range_message_index():
    report = {
        "scores": {"context_management": 5},
        "issues": [
            {"message_index": 3, "category": "ok"},
            {"message_index": 29, "category": "cross_session"},
            {"message_index": -1, "category": "bad"},
        ],
    }
    out = sanitize_qa_report(report, session_id="sess_x", message_count=24)
    assert len(out["issues"]) == 1
    assert out["issues"][0]["message_index"] == 3
    assert out["sanitization"]["dropped_issue_count"] == 2


def test_keeps_issues_without_message_index():
    report = {"issues": [{"category": "general", "description": "no index"}]}
    out = sanitize_qa_report(report, session_id="sess_x", message_count=10)
    assert len(out["issues"]) == 1
    assert "sanitization" not in out
