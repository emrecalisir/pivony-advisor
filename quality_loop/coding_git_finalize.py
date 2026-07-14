"""Post-cursor git finalize: validate, snapshot, commit, and push file fixes."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality_loop.git_branch import ensure_git_branch, git_push_command, git_target_branch, resolve_git_repo
from quality_loop.python_syntax import is_python_path, validate_python_source


@dataclass(frozen=True)
class RepoGitState:
    slug: str
    path: Path
    head: str
    dirty: tuple[str, ...]


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    name = os.environ.get("QUALITY_LOOP_GIT_USER_NAME", "quality-loop").strip() or "quality-loop"
    email = os.environ.get("QUALITY_LOOP_GIT_USER_EMAIL", "quality-loop@pivony.local").strip()
    env.setdefault("GIT_AUTHOR_NAME", name)
    env.setdefault("GIT_AUTHOR_EMAIL", email)
    env.setdefault("GIT_COMMITTER_NAME", name)
    env.setdefault("GIT_COMMITTER_EMAIL", email)
    return env


def _git_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_ALLOW_GIT_PUSH", "").lower() in ("1", "true", "yes")


def list_write_repos() -> list[tuple[str, Path]]:
    from quality_loop.repo_scope import effective_write_repo_path, read_scope, repo_path

    scope = read_scope()
    rows: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for slug in [scope.get("write_repo"), *(scope.get("extra_write_repos") or [])]:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        if slug == scope.get("write_repo"):
            path = effective_write_repo_path(slug)
        else:
            path = repo_path(slug)
        if path and path.is_dir():
            rows.append((slug, path.resolve()))
    return rows


def capture_repo_states() -> list[RepoGitState]:
    states: list[RepoGitState] = []
    for slug, path in list_write_repos():
        head_proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
        dirty_proc = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        dirty = tuple(
            line[3:].strip()
            for line in (dirty_proc.stdout or "").splitlines()
            if len(line) >= 4
        )
        states.append(RepoGitState(slug=slug, path=path, head=head, dirty=dirty))
    return states


def pull_write_repos() -> list[str]:
    messages: list[str] = []
    branch = git_target_branch()
    for slug, path in list_write_repos():
        ok, detail = ensure_git_branch(path, env=_git_env())
        if not ok:
            messages.append(f"⚠ {slug}: {detail}")
            continue
        proc = subprocess.run(
            ["git", "-C", str(path), "pull", "--ff-only", "origin", branch],
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        if proc.returncode == 0:
            messages.append(f"✓ pulled {slug}/{branch}")
        else:
            err = (proc.stderr or proc.stdout or "pull failed").strip()
            messages.append(f"⚠ pull {slug}: {err[:240]}")
    return messages


def _changed_files(before: RepoGitState, after: RepoGitState) -> list[str]:
    files: set[str] = set()
    if before.head and after.head and before.head != after.head:
        proc = subprocess.run(
            ["git", "-C", str(after.path), "diff", "--name-only", before.head, after.head],
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        if proc.returncode == 0:
            files.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    for rel in after.dirty:
        files.add(rel)
    return sorted(files)


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _git_show(repo: Path, rev: str, rel: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{rel}"],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def finalize_cursor_fixes(
    before_states: list[RepoGitState],
    *,
    job_id: str = "",
    qa_report: dict[str, Any] | None = None,
    runtime: str = "local",
) -> tuple[dict[str, Any], list[str]]:
    """Build fixes payload and log lines from git state after Cursor coding."""
    from quality_loop.fix_snapshots import record_fix_snapshot

    try:
        from quality_loop.deploy_gate import (
            auto_deploy_enabled,
            git_push_allowed,
            push_requires_approval,
            queue_push_approval,
            run_canary_deploy,
        )
    except ImportError:
        auto_deploy_enabled = lambda: False  # type: ignore[assignment,misc]
        git_push_allowed = None  # type: ignore[assignment]
        push_requires_approval = lambda: False  # type: ignore[assignment,misc]
        queue_push_approval = None  # type: ignore[assignment]
        run_canary_deploy = lambda: (False, "deploy_gate unavailable")  # type: ignore[assignment,misc]

    messages: list[str] = []
    if runtime == "cloud":
        messages.extend(pull_write_repos())

    after_map = {state.slug: state for state in capture_repo_states()}
    before_map = {state.slug: state for state in before_states}

    fixes_applied: list[dict[str, Any]] = []
    fixes_skipped: list[dict[str, Any]] = []

    for slug, before in before_map.items():
        after = after_map.get(slug)
        if not after:
            continue
        from quality_loop.git_write_lock import acquire_git_write_lock, release_git_write_lock

        git_lock_fh = None
        try:
            git_lock_fh = acquire_git_write_lock(slug)
            git_path, ok, detail = resolve_git_repo(after.path, env=_git_env())
            if not ok:
                fixes_skipped.append(
                    {
                        "file": "N/A",
                        "repo": slug,
                        "issue": "git branch checkout",
                        "reason": detail,
                    }
                )
                continue
            if git_path.resolve() != after.path.resolve():
                messages.append(f"✓ {slug}: git ops via {git_path.name} ({detail})")
            else:
                messages.append(f"✓ {slug}: {detail}")

            changed = _changed_files(before, after)
            if not changed:
                continue

            for rel in changed:
                full = (after.path / rel).resolve()
                if not str(full).startswith(str(after.path.resolve())):
                    fixes_skipped.append(
                        {
                            "file": rel,
                            "repo": slug,
                            "issue": "path escape",
                            "reason": "refusing to finalize outside repo",
                        }
                    )
                    continue

                before_text = _git_show(after.path, before.head, rel) if before.head else ""
                if not before_text and full.exists():
                    before_text = _read_file(full)
                after_text = _read_file(full) if full.exists() else ""

                if is_python_path(full) and after_text:
                    valid, err = validate_python_source(after_text)
                    if not valid:
                        subprocess.run(
                            ["git", "-C", str(after.path), "checkout", "--", rel],
                            capture_output=True,
                            text=True,
                            env=_git_env(),
                        )
                        fixes_skipped.append(
                            {
                                "file": rel,
                                "repo": slug,
                                "issue": "syntax validation",
                                "reason": f"syntax_error: {err}",
                                "deploy_status": "syntax_error",
                            }
                        )
                        messages.append(f"✗ rolled back {slug}/{rel}: {err}")
                        continue

                commit_hash: str | None = None
                git_push_status = "skipped"
                deploy_status = "file_written_and_valid"

                if job_id:
                    try:
                        record_fix_snapshot(job_id, rel, before_text, after_text, repo=slug)
                    except Exception as exc:
                        messages.append(f"⚠ snapshot {slug}/{rel}: {exc}")

                if _git_allowed():
                    commit_msg = f"[quality-loop] cursor fix {rel}"
                    add_proc = subprocess.run(
                        ["git", "-C", str(git_path), "add", rel],
                        capture_output=True,
                        text=True,
                        env=_git_env(),
                    )
                    if add_proc.returncode != 0:
                        fixes_skipped.append(
                            {
                                "file": rel,
                                "repo": slug,
                                "issue": "git add",
                                "reason": (add_proc.stderr or add_proc.stdout or "add failed").strip(),
                            }
                        )
                        continue
                    commit_proc = subprocess.run(
                        ["git", "-C", str(git_path), "commit", "-m", commit_msg],
                        capture_output=True,
                        text=True,
                        env=_git_env(),
                    )
                    if commit_proc.returncode != 0:
                        err = (commit_proc.stderr or commit_proc.stdout or "commit failed").strip()
                        if "nothing to commit" in err.lower():
                            deploy_status = "file_written_and_valid"
                        else:
                            fixes_skipped.append(
                                {
                                    "file": rel,
                                    "repo": slug,
                                    "issue": "git commit",
                                    "reason": err[:300],
                                }
                            )
                            continue
                    else:
                        rev = subprocess.run(
                            ["git", "-C", str(git_path), "rev-parse", "--short", "HEAD"],
                            capture_output=True,
                            text=True,
                            env=_git_env(),
                        )
                        if rev.returncode == 0 and rev.stdout.strip():
                            commit_hash = rev.stdout.strip()
                        can_push = git_push_allowed(job_id=job_id or None) if git_push_allowed else _git_allowed()
                        if can_push:
                            push_proc = subprocess.run(
                                git_push_command(git_path),
                                capture_output=True,
                                text=True,
                                env=_git_env(),
                            )
                            git_push_status = "success" if push_proc.returncode == 0 else "failed"
                            if push_proc.returncode != 0:
                                deploy_status = "commit_push_failed"
                                messages.append(
                                    f"⚠ push {slug}/{rel}: {(push_proc.stderr or push_proc.stdout or '')[:200]}"
                                )
                            else:
                                deploy_status = "committed_and_pushed"
                                messages.append(f"✓ pushed {slug}/{rel} ({commit_hash})")
                                if auto_deploy_enabled():
                                    ok, dep_msg = run_canary_deploy()
                                    messages.append(f"{'✓' if ok else '⚠'} deploy: {dep_msg}")
                        elif push_requires_approval():
                            deploy_status = "pending_approval"
                            git_push_status = "pending_approval"
                            messages.append(f"⏳ push onayı bekleniyor: {slug}/{rel} ({commit_hash})")
                        else:
                            deploy_status = "committed_not_pushed"
                            git_push_status = "skipped"

                    if job_id and commit_hash:
                        try:
                            from quality_loop.fix_snapshots import annotate_fix_snapshot

                            annotate_fix_snapshot(
                                job_id,
                                rel,
                                repo=slug,
                                commit_hash=commit_hash,
                                commit_message=commit_msg,
                                git_push_status=git_push_status,
                            )
                        except Exception:
                            pass

                fixes_applied.append(
                    {
                        "file": rel,
                        "repo": slug,
                        "issue_fixed": f"Cursor fix: {rel}",
                        "deploy_status": deploy_status,
                        "commit_hash": commit_hash,
                    }
                )
        except Exception as exc:
            fixes_skipped.append(
                {
                    "file": "N/A",
                    "repo": slug,
                    "issue": "git write lock",
                    "reason": str(exc),
                }
            )
        finally:
            release_git_write_lock(git_lock_fh)

    payload: dict[str, Any] = {
        "fixes_applied": fixes_applied,
        "fixes_skipped": fixes_skipped,
        "next_test_scenarios": (qa_report or {}).get("next_test_scenarios") or [],
        "coding_backend": "cursor",
    }
    if job_id and fixes_applied:
        try:
            from quality_loop.deploy_gate import push_requires_approval, queue_push_approval

            if push_requires_approval():
                hashes = [
                    str(f.get("commit_hash"))
                    for f in fixes_applied
                    if f.get("commit_hash") and f.get("deploy_status") == "pending_approval"
                ]
                if hashes:
                    queue_push_approval(
                        job_id=job_id,
                        session_id=None,
                        fixes=fixes_applied,
                        commit_hashes=hashes,
                    )
        except Exception:
            pass
    return payload, messages
