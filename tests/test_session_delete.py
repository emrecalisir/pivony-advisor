"""Tests for session file deletion."""

from __future__ import annotations

import json

import pytest

from quality_loop import session_store as store


@pytest.fixture
def isolated_outputs(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    runs = tmp_path / "runs"
    sessions.mkdir()
    runs.mkdir()
    monkeypatch.setattr(store, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(store, "RUNS_DIR", runs)
    return sessions, runs


def _write_session(path, session_id: str) -> None:
    path.write_text(
        json.dumps({"session_id": session_id, "messages": []}),
        encoding="utf-8",
    )


def test_delete_session_files_removes_session_and_run_mirror(isolated_outputs):
    sessions, runs = isolated_outputs
    sid = "sess_abc123"
    _write_session(sessions / "sess_abc123.json", sid)
    (runs / "sess_abc123.json").write_text(
        json.dumps({"session_id": sid, "cycle_id": sid}),
        encoding="utf-8",
    )

    result = store.delete_session_files([sid])

    assert result["deleted"] == [sid]
    assert not (sessions / "sess_abc123.json").exists()
    assert "sess_abc123.json" in result["run_files_removed"]


def test_delete_session_files_missing(isolated_outputs):
    result = store.delete_session_files(["sess_missing"])
    assert result["deleted"] == []
    assert result["missing"] == ["sess_missing"]


def test_list_all_session_ids(isolated_outputs):
    sessions, _ = isolated_outputs
    _write_session(sessions / "sess_one.json", "sess_one")
    _write_session(sessions / "sess_two.json", "sess_two")
    assert sorted(store.list_all_session_ids()) == ["sess_one", "sess_two"]
