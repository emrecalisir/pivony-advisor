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


def _snapshot_key(repo: str | None, file_path: str) -> str:
    if repo:
        return f"{repo}:{file_path}"
    return file_path


def split_repo_file(file_path: str) -> tuple[str | None, str]:
    """Split agent file path into (repo_slug, path relative to repo root)."""
    from quality_loop.repo_scope import read_scope

    normalized = (file_path or "").strip().lstrip("/")
    if not normalized:
        return None, ""
    scope = read_scope()
    known = {r["id"] for r in scope.get("repos") or []}
    if "/" in normalized:
        prefix, rest = normalized.split("/", 1)
        if prefix in known:
            return prefix, rest
    return scope.get("write_repo"), normalized


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


def record_fix_snapshot(
    job_id: str,
    file_path: str,
    before: str,
    after: str,
    *,
    repo: str | None = None,
) -> dict[str, Any]:
    if not job_id:
        return {}
    inferred_repo, rel = split_repo_file(file_path)
    repo_slug = repo or inferred_repo
    rel_path = rel or file_path
    diff = unified_diff(before, after, rel_path)
    added, removed = _count_diff_lines(diff)
    entry: dict[str, Any] = {
        "file": rel_path,
        "repo": repo_slug,
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
    key = _snapshot_key(repo_slug, rel_path)
    replaced = False
    for i, row in enumerate(rows):
        row_key = _snapshot_key(row.get("repo"), str(row.get("file") or ""))
        if row_key == key or (not row.get("repo") and row.get("file") == rel_path):
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
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        file_path = str(row.get("file") or "")
        if not file_path:
            continue
        repo = row.get("repo")
        out[_snapshot_key(repo, file_path)] = row
        if file_path not in out:
            out[file_path] = row
    return out


def _repo_root_for_slug(repo_slug: str | None) -> Path | None:
    if repo_slug:
        from quality_loop.repo_scope import repo_path

        path = repo_path(repo_slug)
        if path:
            return path
    return Path(os.environ.get("PIVONY_REPO_ROOT", _PACKAGE_ROOT.parent))


def git_diff_for_file(file_path: str, *, repo: str | None = None) -> str | None:
    repo_slug, rel = split_repo_file(file_path)
    repo_root = _repo_root_for_slug(repo or repo_slug)
    if not repo_root:
        return None
    full = (repo_root / rel).resolve()
    if not str(full).startswith(str(repo_root.resolve())) or not full.exists():
        return None
    for args in (["diff", "HEAD", "--", rel], ["diff", "--", rel]):
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def _qa_issue_at(qa_report: dict[str, Any] | None, index: Any) -> dict[str, Any] | None:
    issues = (qa_report or {}).get("issues") or []
    if index is None:
        return None
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < len(issues) and isinstance(issues[idx], dict):
        return issues[idx]
    return None


def _normalize_fix_row(row: dict[str, Any], qa_report: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(row)
    raw_file = str(out.get("file") or "")
    if raw_file and raw_file != "N/A":
        repo_slug, rel_path = split_repo_file(raw_file)
        if repo_slug and not out.get("repo"):
            out["repo"] = repo_slug
        if rel_path and raw_file != rel_path:
            out["file"] = rel_path
            out.setdefault("file_raw", raw_file)
    idx = out.get("qa_issue_index")
    if idx is None and out.get("qa_issue_id") is not None:
        idx = out.get("qa_issue_id")
        out["qa_issue_index"] = idx
    issue = _qa_issue_at(qa_report, idx)
    if issue:
        out.setdefault("qa_issue_index", idx)
        out.setdefault("qa_severity", issue.get("severity"))
        out.setdefault("qa_category", issue.get("category"))
        out.setdefault("qa_issue_description", issue.get("description"))
        out.setdefault("qa_message_index", issue.get("message_index"))
    return out


def enrich_fixes(
    fixes: dict[str, Any] | None,
    *,
    job_id: str | None = None,
    qa_report: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not fixes:
        return fixes
    snapshots = load_snapshots(job_id)
    out = dict(fixes)
    applied = []
    for item in fixes.get("fixes_applied") or []:
        if not isinstance(item, dict):
            continue
        row = _normalize_fix_row(item, qa_report)
        repo = row.get("repo")
        rel = str(row.get("file") or "")
        snap = snapshots.get(_snapshot_key(repo, rel)) or snapshots.get(rel)
        if snap:
            row.setdefault("repo", snap.get("repo"))
            row.setdefault("diff", snap.get("diff"))
            row.setdefault("lines_added", snap.get("lines_added"))
            row.setdefault("lines_removed", snap.get("lines_removed"))
            row.setdefault("recorded_at", snap.get("recorded_at"))
        elif rel and not row.get("diff"):
            diff = git_diff_for_file(rel, repo=repo if isinstance(repo, str) else None)
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
            skipped.append(_normalize_fix_row({"file": "N/A", "issue": item, "reason": ""}, qa_report))
        elif isinstance(item, dict):
            row = dict(item)
            if "issue" not in row and row.get("reason"):
                row["issue"] = row.get("reason")
            skipped.append(_normalize_fix_row(row, qa_report))
    out["fixes_skipped"] = skipped
    return out
