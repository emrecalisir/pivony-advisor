"""Tests for coding-agent git branch pinning."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from quality_loop.git_branch import (
    current_git_branch,
    ensure_git_branch,
    git_push_command,
    git_target_branch,
)


def test_git_target_branch_defaults_to_development(monkeypatch):
    monkeypatch.delenv("QUALITY_LOOP_GIT_BRANCH", raising=False)
    assert git_target_branch() == "development"


def test_git_target_branch_respects_env(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_GIT_BRANCH", "feature/x")
    assert git_target_branch() == "feature/x"


def test_git_push_command_targets_origin_branch(monkeypatch):
    monkeypatch.delenv("QUALITY_LOOP_GIT_BRANCH", raising=False)
    assert git_push_command(Path("/tmp/repo")) == [
        "git",
        "-C",
        "/tmp/repo",
        "push",
        "origin",
        "development",
    ]


def test_ensure_git_branch_noop_when_already_on_target():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-b", "development"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, check=True, capture_output=True)
        ok, detail = ensure_git_branch(repo)
        assert ok is True
        assert detail == "on development"
        assert current_git_branch(repo) == "development"


def test_ensure_git_branch_checkout_from_other_branch():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-b", "development"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "branch", "other"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "other"], cwd=repo, check=True, capture_output=True)
        ok, detail = ensure_git_branch(repo)
        assert ok is True
        assert "development" in detail
        assert current_git_branch(repo) == "development"


def test_ensure_git_branch_fails_for_non_repo(tmp_path):
    ok, detail = ensure_git_branch(tmp_path / "missing")
    assert ok is False
    assert "not a git repository" in detail
