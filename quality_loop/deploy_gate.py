"""Human approval + canary deploy before git push."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
QUEUE_PATH = _PACKAGE_ROOT / "outputs" / "deploy_queue.json"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue() -> dict[str, Any]:
    if not QUEUE_PATH.exists():
        return {"pending": [], "history": []}
    try:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"pending": [], "history": []}


def _save_queue(data: dict[str, Any]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def git_commit_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_ALLOW_GIT_PUSH", "").lower() in ("1", "true", "yes")


def push_requires_approval() -> bool:
    raw = os.environ.get("QUALITY_LOOP_REQUIRE_PUSH_APPROVAL", "true").strip().lower()
    return raw in ("1", "true", "yes")


def git_push_allowed(*, job_id: str | None = None) -> bool:
    if not git_commit_allowed():
        return False
    if not push_requires_approval():
        return True
    if not job_id:
        return False
    data = _load_queue()
    for row in data.get("pending") or []:
        if row.get("job_id") == job_id and row.get("status") == "approved":
            return True
    return False


def deploy_target() -> str:
    return os.environ.get("QUALITY_LOOP_DEPLOY_TARGET", "dev").strip().lower() or "dev"


def deploy_command() -> str:
    if deploy_target() == "prod":
        return os.environ.get("DEPLOY_CMD", "systemctl restart pivony-advisor").strip()
    return os.environ.get(
        "DEPLOY_CMD_DEV",
        os.environ.get("DEPLOY_CMD", "systemctl restart pivony-advisor-dev"),
    ).strip()


def auto_deploy_enabled() -> bool:
    return os.environ.get("QUALITY_LOOP_AUTO_DEPLOY", "").lower() in ("1", "true", "yes")


def dev_auto_approve_enabled() -> bool:
    """Dev: keep approval gate but auto-approve when verification/tests pass."""
    raw = os.environ.get("QUALITY_LOOP_DEV_AUTO_APPROVE", "").strip().lower()
    return raw in ("1", "true", "yes") and deploy_target() == "dev"


def commits_ahead_of_origin(
    repo: Path,
    *,
    head: str | None = None,
    origin: str | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Short hashes of commits reachable from HEAD but not from origin/<branch>."""
    from quality_loop.git_branch import git_target_branch

    git_env = env or os.environ.copy()
    branch = git_target_branch()
    if not origin:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", f"origin/{branch}"],
            capture_output=True,
            text=True,
            env=git_env,
        )
        if proc.returncode != 0:
            return []
        origin = proc.stdout.strip()
    if not head:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            env=git_env,
        )
        if proc.returncode != 0:
            return []
        head = proc.stdout.strip()
    if not origin or not head or origin == head:
        return []
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%h", f"{origin}..{head}"],
        capture_output=True,
        text=True,
        env=git_env,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def job_push_was_approved(job_id: str) -> bool:
    data = _load_queue()
    for row in data.get("pending") or []:
        if row.get("job_id") == job_id and row.get("status") in ("approved", "pushed"):
            return True
    for row in data.get("history") or []:
        if row.get("job_id") == job_id and row.get("status") == "pushed":
            return True
    return False


def maybe_auto_approve_dev(job_id: str) -> dict[str, Any] | None:
    if not dev_auto_approve_enabled():
        return None
    try:
        return approve_push(job_id, approved_by="dev_auto")
    except KeyError:
        return None


def process_push_gate_after_finalize(
    *,
    job_id: str,
    before_states: list[Any],
    after_states: list[Any],
    fixes_applied: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    After Cursor/finalize: detect unpushed commits and unauthorized origin advances.
    Queues push approval even when finalize saw 'nothing to commit' (cloud already committed).
    """
    from quality_loop.coding_git_finalize import _git_env

    git_env = _git_env()
    before_map = {s.slug: s for s in before_states}
    after_map = {s.slug: s for s in after_states}
    unauthorized: list[dict[str, Any]] = []
    ahead_all: list[str] = []
    messages: list[str] = []

    for slug, after in after_map.items():
        before = before_map.get(slug)
        if not before:
            continue
        subprocess.run(
            ["git", "-C", str(after.path), "fetch", "origin", deploy_target_branch(), "--quiet"],
            capture_output=True,
            text=True,
            env=git_env,
            timeout=60,
        )
        origin_after = _rev_parse(after.path, f"origin/{deploy_target_branch()}", env=git_env)
        origin_before = before.origin_head or ""

        if (
            origin_before
            and origin_after
            and origin_before != origin_after
            and not job_push_was_approved(job_id)
        ):
            unauthorized.append(
                {
                    "repo": slug,
                    "origin_before": origin_before[:12],
                    "origin_after": origin_after[:12],
                }
            )
            messages.append(
                f"⚠ {slug}: origin advanced without deploy_gate approval "
                f"({origin_before[:7]}→{origin_after[:7]})"
            )

        ahead = commits_ahead_of_origin(
            after.path,
            head=after.head,
            origin=origin_after or None,
            env=git_env,
        )
        ahead_all.extend(ahead)

        for fix in fixes_applied:
            if fix.get("repo") == slug and fix.get("deploy_status") == "file_written_and_valid":
                if ahead and push_requires_approval() and not git_push_allowed(job_id=job_id):
                    fix["deploy_status"] = "pending_approval"
                    fix["git_push_status"] = "pending_approval"
                    if not fix.get("commit_hash") and ahead:
                        fix["commit_hash"] = ahead[0]

    gate: dict[str, Any] = {
        "commits_ahead": ahead_all,
        "unauthorized_origin_push": unauthorized,
        "push_queued": False,
    }

    if not git_commit_allowed() or not push_requires_approval():
        return gate

    hashes = list(dict.fromkeys(ahead_all))
    pending_fixes = [f for f in fixes_applied if f.get("deploy_status") == "pending_approval"]
    if hashes or pending_fixes:
        queue_push_approval(
            job_id=job_id,
            session_id=None,
            fixes=fixes_applied,
            commit_hashes=hashes or [
                str(f.get("commit_hash")) for f in pending_fixes if f.get("commit_hash")
            ],
        )
        gate["push_queued"] = True
        messages.append(f"⏳ push onayı kuyruğa alındı ({len(hashes)} commit)")
        auto = maybe_auto_approve_dev(job_id)
        if auto:
            gate["auto_approved"] = True
            messages.append("✓ dev auto-approve uygulandı")

    gate["messages"] = messages
    return gate


def deploy_target_branch() -> str:
    from quality_loop.git_branch import git_target_branch

    return git_target_branch()


def _rev_parse(repo: Path, ref: str, *, env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def queue_push_approval(
    *,
    job_id: str,
    session_id: str | None,
    fixes: list[dict[str, Any]],
    commit_hashes: list[str],
) -> dict[str, Any]:
    data = _load_queue()
    pending = [r for r in data.get("pending") or [] if r.get("job_id") != job_id]
    entry = {
        "job_id": job_id,
        "session_id": session_id,
        "status": "pending",
        "commit_hashes": commit_hashes,
        "fix_count": len(fixes),
        "fixes_preview": [
            {
                "file": f.get("file"),
                "repo": f.get("repo"),
                "qa_issue_index": f.get("qa_issue_index"),
                "commit_hash": f.get("commit_hash"),
            }
            for f in fixes[:12]
            if isinstance(f, dict)
        ],
        "queued_at": _utcnow_iso(),
        "deploy_target": deploy_target(),
    }
    pending.insert(0, entry)
    data["pending"] = pending
    _save_queue(data)
    return entry


def list_pending_approvals() -> list[dict[str, Any]]:
    data = _load_queue()
    return list(data.get("pending") or [])


def approve_push(job_id: str, *, approved_by: str | None = None) -> dict[str, Any]:
    data = _load_queue()
    found: dict[str, Any] | None = None
    pending = []
    for row in data.get("pending") or []:
        if row.get("job_id") == job_id:
            found = dict(row)
            found["status"] = "approved"
            found["approved_at"] = _utcnow_iso()
            found["approved_by"] = approved_by or "ui"
            pending.append(found)
        elif row.get("status") == "pending":
            pending.append(row)
    if not found:
        raise KeyError(job_id)
    data["pending"] = pending
    hist = data.get("history") or []
    hist.insert(0, found)
    data["history"] = hist[:50]
    _save_queue(data)
    return found


def mark_pushed(job_id: str) -> None:
    data = _load_queue()
    pending = []
    for row in data.get("pending") or []:
        if row.get("job_id") == job_id:
            row = dict(row)
            row["status"] = "pushed"
            row["pushed_at"] = _utcnow_iso()
            hist = data.get("history") or []
            hist.insert(0, row)
            data["history"] = hist[:50]
        else:
            pending.append(row)
    data["pending"] = pending
    _save_queue(data)


def push_approved_job(job_id: str) -> dict[str, Any]:
    """Push write repos after human approval."""
    from quality_loop.coding_git_finalize import _git_env, list_write_repos
    from quality_loop.git_branch import git_push_command

    if not git_commit_allowed():
        raise RuntimeError("QUALITY_LOOP_ALLOW_GIT_PUSH is disabled")

    data = _load_queue()
    entry: dict[str, Any] | None = None
    for row in data.get("pending") or []:
        if row.get("job_id") == job_id and row.get("status") == "approved":
            entry = row
            break
    if not entry:
        raise KeyError(job_id)

    repo_results: list[dict[str, Any]] = []
    for slug, path in list_write_repos():
        proc = subprocess.run(
            git_push_command(path),
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        repo_results.append(
            {
                "repo": slug,
                "ok": proc.returncode == 0,
                "stderr": (proc.stderr or proc.stdout or "")[:300],
            }
        )

    mark_pushed(job_id)
    deploy_ok, deploy_msg = (False, "")
    if auto_deploy_enabled():
        deploy_ok, deploy_msg = run_canary_deploy()
    return {
        "job_id": job_id,
        "repos": repo_results,
        "deploy_ok": deploy_ok,
        "deploy_message": deploy_msg,
    }


def run_canary_deploy() -> tuple[bool, str]:
    cmd = deploy_command()
    if not cmd:
        return False, "DEPLOY_CMD not set"
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "deploy failed")[:400]
    return True, f"deploy ok ({deploy_target()}): {cmd}"
