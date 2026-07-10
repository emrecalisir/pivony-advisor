"""Pin coding-agent git operations to a fixed branch (default: development)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git_target_branch() -> str:
    return os.environ.get("QUALITY_LOOP_GIT_BRANCH", "development").strip() or "development"


def current_git_branch(repo: Path, *, env: dict[str, str] | None = None) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
    )
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def ensure_git_branch(repo: Path, *, env: dict[str, str] | None = None) -> tuple[bool, str]:
    """Checkout QUALITY_LOOP_GIT_BRANCH before writes/commits. Returns (ok, detail)."""
    git_env = env or os.environ.copy()
    branch = git_target_branch()
    current = current_git_branch(repo, env=git_env)
    if current is None:
        return False, f"not a git repository: {repo}"
    if current == branch:
        return True, f"on {branch}"

    proc = subprocess.run(
        ["git", "-C", str(repo), "checkout", branch],
        capture_output=True,
        text=True,
        env=git_env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "checkout failed").strip()
        return False, f"could not checkout {branch} (was on {current}): {err}"
    return True, f"switched {current} → {branch}"


def git_push_command(repo: Path) -> list[str]:
    branch = git_target_branch()
    return ["git", "-C", str(repo), "push", "origin", branch]
