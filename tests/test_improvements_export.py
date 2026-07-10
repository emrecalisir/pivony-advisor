"""Tests for coding agent / improvements export."""

from __future__ import annotations

from quality_loop.ui.export_builder import (
    build_improvements_export_json,
    build_improvements_export_markdown,
    export_filename,
)


def test_build_improvements_export_json():
    meta = {
        "run_id": "sess_abc",
        "fixes": {
            "fixes_applied": [{"file": "src/x.py", "issue_fixed": "fix one"}],
            "fixes_skipped": [{"file": "N/A", "issue": "api only", "reason": "out of scope"}],
            "next_test_scenarios": ["retry list_dashboards"],
        },
    }
    out = build_improvements_export_json(session_id="sess_abc", meta=meta)
    assert out["product"] == "pivony-quality-loop-improvements"
    assert out["stats"]["applied_count"] == 1
    assert out["stats"]["skipped_count"] == 1


def test_export_filename_improvements():
    name = export_filename("sess_abc123", "json", kind="improvements")
    assert "pivony-quality-loop-improvements" in name
    assert name.endswith(".json")


def test_build_improvements_export_markdown():
    md = build_improvements_export_markdown(
        session_id="sess_abc",
        meta={"fixes": {"fixes_applied": [{"file": "src/x.py", "issue_fixed": "done"}]}},
    )
    assert "Coding Agent" in md
    assert "src/x.py" in md
