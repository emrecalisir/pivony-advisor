"""Tests for hybrid Cursor coding backend."""

from __future__ import annotations

from quality_loop.coding_cursor import (
    build_cursor_coding_prompt,
    coding_backend,
    is_cursor_coding_enabled,
)


def test_coding_backend_defaults_to_cursor(monkeypatch):
    monkeypatch.delenv("QUALITY_LOOP_CODING_BACKEND", raising=False)
    assert coding_backend() == "cursor"


def test_is_cursor_coding_disabled_without_api_key(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_CODING_BACKEND", "cursor")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    assert is_cursor_coding_enabled() is False


def test_is_cursor_coding_disabled_for_crewai_backend(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_CODING_BACKEND", "crewai")
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    assert is_cursor_coding_enabled() is False


def test_build_cursor_coding_prompt_includes_qa_and_branch(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_GIT_BRANCH", "development")
    qa = {
        "overall_verdict": "fail",
        "issues": [{"severity": "critical", "description": "tool routing bug", "fix_hint": "fix x"}],
    }
    prompt = build_cursor_coding_prompt(qa, session_id="sess_test", sector="default")
    assert "development" in prompt
    assert "tool routing bug" in prompt
    assert "fixes_applied" in prompt
    assert "masterr_root" in prompt or "write_repo" in prompt
