"""Tests for Python syntax gate on coding-agent file writes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from quality_loop.apply_fix_write import validate_and_write_file
from quality_loop.fix_snapshots import _infer_deploy_status, record_fix_snapshot
from quality_loop.python_syntax import is_python_path, validate_python_source


def test_validate_python_source_accepts_valid_code():
    ok, err = validate_python_source("def foo():\n    return 1\n")
    assert ok is True
    assert err is None


def test_validate_python_source_rejects_invalid_code():
    ok, err = validate_python_source('x = """unclosed\n')
    assert ok is False
    assert "line" in (err or "")


def test_is_python_path():
    assert is_python_path("src/foo.py") is True
    assert is_python_path("README.md") is False


def test_infer_deploy_status_prefers_explicit():
    assert _infer_deploy_status({"deploy_status": "syntax_error"}) == "syntax_error"


def test_infer_deploy_status_valid_write():
    assert _infer_deploy_status({"diff": "+x", "lines_added": 1}) == "file_written_and_valid"


def test_validate_and_write_rejects_syntax_before_write():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "broken.py"
        bad = 'def broken():\n    return """escaped wrong\n'
        result = validate_and_write_file(target, bad)
        assert result.ok is False
        assert "syntax_error" in result.message
        assert not target.exists()


def test_validate_and_write_roundtrip_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "good.py"
        original = "def ok():\n    return 1\n"
        target.write_text(original, encoding="utf-8")
        valid = "def ok():\n    return 2\n"
        calls = {"n": 0}

        def fake_validate(source: str):
            calls["n"] += 1
            if calls["n"] == 1:
                return True, None
            return False, "line 1: corrupt"

        with patch("quality_loop.apply_fix_write.validate_python_source", side_effect=fake_validate):
            result = validate_and_write_file(target, valid, original)

        assert result.ok is False
        assert result.rolled_back is True
        assert target.read_text(encoding="utf-8") == original


def test_validate_and_write_accepts_valid_python():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "new_module.py"
        content = "def hello():\n    return 'world'\n"
        result = validate_and_write_file(target, content)
        assert result.ok is True
        assert result.wrote is True
        assert "file_written_and_valid" in result.message
        assert target.read_text(encoding="utf-8") == content


def test_record_fix_snapshot_sets_valid_status(tmp_path, monkeypatch):
    monkeypatch.setattr("quality_loop.fix_snapshots.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("quality_loop.fix_snapshots.SNAPSHOTS_DIR", tmp_path / "fix_snapshots")
    entry = record_fix_snapshot("job_test", "a.py", "", "x = 1\n")
    assert entry.get("deploy_status") == "file_written_and_valid"
