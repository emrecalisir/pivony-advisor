"""Tests for Cursor external memory / prompt context."""

from __future__ import annotations

import json
from pathlib import Path

from quality_loop.cursor_context import (
    build_known_open_issues,
    build_previous_fixes_summary,
    render_cursor_prompt_template,
)


def test_render_cursor_prompt_includes_placeholders():
    prompt = render_cursor_prompt_template(
        repo_scope="- write_repo: pivony-advisor",
        coding_brief="minimal fixes",
        qa_report_json='{"issues": []}',
        previous_fixes_summary="- [2026-07-09] pivony-advisor/src/x.py: fix (commit abc)",
        known_open_issues="- [QA #0] high: api scope",
        session_id="sess_test",
        branch="development",
    )
    assert "ÖNCEKİ FIX ÖZETİ" in prompt
    assert "abc" in prompt
    assert "Kural 2" in prompt
    assert "failed_validation" in prompt
    assert "sess_test" in prompt


def test_build_known_open_issues_flags_api_hints():
    qa = {
        "issues": [
            {
                "severity": "high",
                "description": "dashboard 403",
                "fix_hint": "pivony-api route mapping",
            }
        ]
    }
    text = build_known_open_issues(qa)
    assert "pivony-api" in text.lower() or "scope" in text.lower()


def test_build_previous_fixes_summary_empty_when_no_cycles(monkeypatch):
    monkeypatch.setattr("quality_loop.cycle_store.list_completed_cycles", lambda: [])
    assert "önceki fix kaydı yok" in build_previous_fixes_summary()
