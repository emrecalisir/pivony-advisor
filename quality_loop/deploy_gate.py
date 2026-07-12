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
