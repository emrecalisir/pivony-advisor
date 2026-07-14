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
    resolve_git_repo,
    worktree_path_on_branch,
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


def _setup_main_dev_worktrees(main: Path, dev: Path) -> None:
    main.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=main, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=main, check=True, capture_output=True)
    subprocess.run(["git", "branch", "development"], cwd=main, check=True, capture_output=True)
    subprocess.run(["git", "worktree", "add", str(dev), "development"], cwd=main, check=True, capture_output=True)


def test_worktree_path_on_branch_finds_linked_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main"
        dev = Path(tmp) / "dev"
        _setup_main_dev_worktrees(main, dev)
        assert worktree_path_on_branch(main, "development") == dev.resolve()


def test_ensure_git_branch_accepts_active_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main"
        dev = Path(tmp) / "dev"
        _setup_main_dev_worktrees(main, dev)
        ok, detail = ensure_git_branch(main)
        assert ok is True
        assert "worktree" in detail


def test_resolve_git_repo_points_to_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main"
        dev = Path(tmp) / "dev"
        _setup_main_dev_worktrees(main, dev)
        path, ok, _ = resolve_git_repo(main)
        assert ok is True
        assert path.resolve() == dev.resolve()


def test_effective_write_repo_path_prefers_dev_worktree(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main = root / "pivony-advisor"
        dev = root / "pivony-advisor-dev"
        _setup_main_dev_worktrees(main, dev)

        repos = [
            {"id": "pivony-advisor", "path": str(main)},
            {"id": "pivony-advisor-dev", "path": str(dev)},
        ]

        def fake_read_scope():
            return {
                "write_repo": "pivony-advisor",
                "read_repos": [],
                "extra_write_repos": [],
                "blocked_write_repos": [],
                "repos": repos,
            }

        monkeypatch.setattr("quality_loop.repo_scope.read_scope", fake_read_scope)
        monkeypatch.delenv("PIVONY_REPO_ROOT", raising=False)
        monkeypatch.delenv("QUALITY_LOOP_WRITE_REPO_PATH", raising=False)
        from quality_loop.repo_scope import effective_write_repo_path

        assert effective_write_repo_path().resolve() == dev.resolve()
