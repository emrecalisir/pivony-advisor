"""Persist unified diffs when Coding Agent applies file fixes."""

from __future__ import annotations

import difflib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = _PACKAGE_ROOT / "outputs"
SNAPSHOTS_DIR = OUTPUT_DIR / "fix_snapshots"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_job_id(job_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)


def _manifest_path(job_id: str) -> Path:
    return SNAPSHOTS_DIR / _safe_job_id(job_id) / "manifest.json"


def unified_diff(before: str, after: str, file_path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )


def _count_diff_lines(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def record_fix_snapshot(job_id: str, file_path: str, before: str, after: str) -> dict[str, Any]:
    if not job_id:
        return {}
    diff = unified_diff(before, after, file_path)
    added, removed = _count_diff_lines(diff)
    entry: dict[str, Any] = {
        "file": file_path,
        "diff": diff,
        "lines_added": added,
        "lines_removed": removed,
        "recorded_at": _utcnow_iso(),
    }
    path = _manifest_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        except (json.JSONDecodeError, OSError):
            rows = []
    replaced = False
    for i, row in enumerate(rows):
        if row.get("file") == file_path:
            rows[i] = entry
            replaced = True
            break
    if not replaced:
        rows.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return entry


def load_snapshots(job_id: str | None) -> dict[str, dict[str, Any]]:
    if not job_id:
        return {}
    path = _manifest_path(job_id)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(r.get("file")): r for r in rows if r.get("file")}


def _repo_root() -> Path:
    return Path(os.environ.get("PIVONY_REPO_ROOT", _PACKAGE_ROOT.parent))


def git_diff_for_file(file_path: str) -> str | None:
    repo = _repo_root()
    full = (repo / file_path).resolve()
    if not str(full).startswith(str(repo.resolve())) or not full.exists():
        return None
    for args in (["diff", "HEAD", "--", file_path], ["diff", "--", file_path]):
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def enrich_fixes(fixes: dict[str, Any] | None, *, job_id: str | None = None) -> dict[str, Any] | None:
    if not fixes:
        return fixes
    snapshots = load_snapshots(job_id)
    out = dict(fixes)
    applied = []
    for item in fixes.get("fixes_applied") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        snap = snapshots.get(row.get("file") or "")
        if snap:
            row.setdefault("diff", snap.get("diff"))
            row.setdefault("lines_added", snap.get("lines_added"))
            row.setdefault("lines_removed", snap.get("lines_removed"))
            row.setdefault("recorded_at", snap.get("recorded_at"))
        elif row.get("file") and not row.get("diff"):
            diff = git_diff_for_file(str(row["file"]))
            if diff:
                added, removed = _count_diff_lines(diff)
                row["diff"] = diff
                row["lines_added"] = added
                row["lines_removed"] = removed
                row["diff_source"] = "git_worktree"
        applied.append(row)
    out["fixes_applied"] = applied
    skipped = []
    for item in fixes.get("fixes_skipped") or []:
        if isinstance(item, str):
            skipped.append({"file": "N/A", "issue": item, "reason": ""})
        elif isinstance(item, dict):
            skipped.append(item)
    out["fixes_skipped"] = skipped
    return out
