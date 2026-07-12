"""Distilled cross-job context for Cursor coding prompts (external memory)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
_SNAPSHOTS_DIR = _PACKAGE_ROOT / "outputs" / "fix_snapshots"


def _context_job_limit() -> int:
    raw = os.environ.get("QUALITY_LOOP_CURSOR_CONTEXT_JOBS", "10").strip()
    try:
        return max(1, min(30, int(raw)))
    except ValueError:
        return 10


def _date_prefix(iso: str | None) -> str:
    if not iso:
        return "????-??-??"
    return iso[:10] if len(iso) >= 10 else iso


def _load_session(session_id: str) -> dict[str, Any] | None:
    from quality_loop.session_store import load_session

    data = load_session(session_id)
    return data if isinstance(data, dict) else None


def _line_for_applied(created: str, fix: dict[str, Any]) -> str:
    repo = fix.get("repo") or "pivony-advisor"
    file_path = fix.get("file") or "?"
    issue = fix.get("issue_fixed") or fix.get("issue") or "fix"
    commit = fix.get("commit_hash") or "—"
    return f"- [{created}] {repo}/{file_path}: {issue} (commit {commit})"


def _line_for_skipped(created: str, fix: dict[str, Any]) -> str:
    repo = fix.get("repo") or "N/A"
    issue = fix.get("issue") or fix.get("reason") or "skipped"
    reason = fix.get("reason") or ""
    suffix = f" — {reason}" if reason and reason != issue else ""
    return f"- [{created}/SKIP] {repo}: {issue}{suffix}"


def _line_for_failed(created: str, fix: dict[str, Any]) -> str:
    file_path = fix.get("file") or "?"
    reason = fix.get("reason") or "validation failed"
    return f"- [{created}/FAIL] {file_path}: {reason}"


def build_previous_fixes_summary(
    *,
    limit: int | None = None,
    exclude_session_id: str | None = None,
) -> str:
    """Distill recent fix history from completed cycles (not raw transcripts)."""
    from quality_loop.cycle_store import list_completed_cycles

    job_limit = limit or _context_job_limit()
    lines: list[str] = []
    seen_jobs = 0

    for row in list_completed_cycles():
        session_id = str(row.get("session_id") or row.get("cycle_id") or "")
        if not session_id or session_id == exclude_session_id:
            continue
        session = _load_session(session_id)
        if not session:
            continue
        fixes = session.get("fixes")
        if not isinstance(fixes, dict):
            continue

        created = _date_prefix(session.get("updated_at") or session.get("created_at"))
        for fix in fixes.get("fixes_applied") or []:
            if isinstance(fix, dict):
                lines.append(_line_for_applied(created, fix))
        for fix in fixes.get("fixes_skipped") or []:
            if isinstance(fix, dict):
                lines.append(_line_for_skipped(created, fix))
        cursor_summary = fixes.get("cursor_summary")
        if isinstance(cursor_summary, dict):
            for fix in cursor_summary.get("failed_validation") or []:
                if isinstance(fix, dict):
                    lines.append(_line_for_failed(created, fix))

        seen_jobs += 1
        if seen_jobs >= job_limit:
            break

    if not lines:
        return "(önceki fix kaydı yok — bu job ilk coding run olabilir)"
    return "\n".join(lines[: job_limit * 4])


def build_known_open_issues(
    qa_report: dict[str, Any] | None,
    *,
    exclude_session_id: str | None = None,
) -> str:
    """Aggregate recurring skips and current QA issues that are likely out-of-scope."""
    lines: list[str] = []
    blocked_markers = ("pivony-api", "scope", "403", "api-dev", "out of scope", "scope dışı")

    if isinstance(qa_report, dict):
        for idx, issue in enumerate(qa_report.get("issues") or []):
            if not isinstance(issue, dict):
                continue
            hint = str(issue.get("fix_hint") or "").lower()
            desc = str(issue.get("description") or "").lower()
            combined = f"{hint} {desc}"
            if any(marker in combined for marker in blocked_markers) or "pivony-api" in hint:
                lines.append(
                    f"- [QA #{idx}] {issue.get('severity', '?')}: "
                    f"{issue.get('description', '')[:120]} "
                    f"(fix_hint scope dışı olabilir)"
                )

    from quality_loop.cycle_store import list_completed_cycles

    skip_counts: dict[str, int] = {}
    for row in list_completed_cycles()[:15]:
        session_id = str(row.get("session_id") or "")
        if not session_id or session_id == exclude_session_id:
            continue
        session = _load_session(session_id)
        if not session:
            continue
        fixes = session.get("fixes") or {}
        for fix in fixes.get("fixes_skipped") or []:
            if not isinstance(fix, dict):
                continue
            key = f"{fix.get('repo') or 'N/A'}: {fix.get('issue') or fix.get('reason') or 'skip'}"
            skip_counts[key] = skip_counts.get(key, 0) + 1

    for key, count in sorted(skip_counts.items(), key=lambda x: -x[1])[:8]:
        if count >= 2:
            lines.append(f"- [TEKRARLAYAN SKIP x{count}] {key}")

    if not lines:
        return "(bilinen açık sorun özeti yok — QA raporundaki tüm issue'lar scope içinde olabilir)"
    return "\n".join(lines)


def render_cursor_prompt_template(
    *,
    repo_scope: str,
    coding_brief: str,
    qa_report_json: str,
    previous_fixes_summary: str,
    known_open_issues: str,
    session_id: str | None = None,
    branch: str = "development",
) -> str:
    template_path = _PACKAGE_ROOT / "config" / "cursor_coding_prompt.md"
    template = template_path.read_text(encoding="utf-8")
    header = (
        f"Session: {session_id or 'n/a'}\n"
        f"Git branch: ALWAYS work on `{branch}` only.\n\n"
    )
    rendered = template.format(
        repo_scope=repo_scope.strip(),
        coding_brief=coding_brief.strip(),
        qa_report_json=qa_report_json.strip(),
        previous_fixes_summary=previous_fixes_summary.strip(),
        known_open_issues=known_open_issues.strip(),
    )
    return header + rendered
