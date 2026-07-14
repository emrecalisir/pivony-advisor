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


def worktree_path_on_branch(repo: Path, branch: str, *, env: dict[str, str] | None = None) -> Path | None:
    """Return a linked worktree path that is already on ``branch``, if any."""
    git_env = env or os.environ.copy()
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        env=git_env,
    )
    if proc.returncode != 0:
        return None
    current_path: Path | None = None
    current_branch: str | None = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1]).resolve()
            current_branch = None
        elif line.startswith("branch ") and current_path is not None:
            ref = line.split(" ", 1)[1].strip()
            current_branch = ref.removeprefix("refs/heads/")
            if current_branch == branch:
                return current_path
    return None


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
        if "worktree" in err.lower() or "already checked out" in err.lower():
            wt = worktree_path_on_branch(repo, branch, env=git_env)
            if wt is not None:
                return True, f"branch {branch} active in worktree {wt}"
        return False, f"could not checkout {branch} (was on {current}): {err}"
    return True, f"switched {current} → {branch}"


def resolve_git_repo(repo: Path, *, env: dict[str, str] | None = None) -> tuple[Path, bool, str]:
    """Pick the repo path to use for git finalize (handles worktree layouts)."""
    git_env = env or os.environ.copy()
    branch = git_target_branch()
    if current_git_branch(repo, env=git_env) == branch:
        return repo, True, f"on {branch}"
    ok, detail = ensure_git_branch(repo, env=git_env)
    if ok and "worktree" in detail:
        wt = worktree_path_on_branch(repo, branch, env=git_env)
        if wt is not None:
            return wt, True, detail
    return repo, ok, detail


def git_push_command(repo: Path) -> list[str]:
    branch = git_target_branch()
    return ["git", "-C", str(repo), "push", "origin", branch]
