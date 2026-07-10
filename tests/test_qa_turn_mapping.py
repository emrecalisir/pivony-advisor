"""Tests for QA issue → turn mapping in quality loop UI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_app_helpers():
    path = Path(__file__).resolve().parents[1] / "quality_loop" / "ui" / "app.py"
    spec = importlib.util.spec_from_file_location("quality_loop.ui.app_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["quality_loop.ui.app_test"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_app_helpers()
_issues_for_turn = _mod._issues_for_turn
_issue_matches_turn = _mod._issue_matches_turn


def test_issue_matches_turn_single_index():
    assert _issue_matches_turn(1, 1)
    assert _issue_matches_turn(3, 2)
    assert not _issue_matches_turn(3, 4)


def test_issue_matches_turn_list_index():
    issue = {"message_index": [1, 3, 5, 7, 9, 13, 15]}
    assert len(_issues_for_turn([issue], 1)) == 1
    assert len(_issues_for_turn([issue], 8)) == 1


def test_issues_for_turn_deduplicates_per_issue():
    issue = {"category": "tool_execution_failure", "message_index": [1, 3]}
    matched = _issues_for_turn([issue], 1)
    assert len(matched) == 1
