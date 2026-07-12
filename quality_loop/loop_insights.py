"""Session trends, baseline, backlog, and issue↔fix traceability."""

from __future__ import annotations

import os
from typing import Any

_ENV_MARKERS = ("429", "403", "rate limit", "resource_exhausted", "dashboard_not_accessible")
_INFRA_CATEGORIES = {"misleading_error"}
_BLOCKED_MARKERS = ("pivony-api", "scope dışı", "out of scope", "api-dev")


def classify_issue(issue: dict[str, Any]) -> str:
    """issue_class: code | env | flaky | blocked"""
    if not isinstance(issue, dict):
        return "code"
    hint = f"{issue.get('fix_hint', '')} {issue.get('description', '')} {issue.get('evidence', '')}".lower()
    category = str(issue.get("category") or "").lower()
    if any(m in hint for m in _BLOCKED_MARKERS) or "pivony-api" in hint:
        return "blocked"
    if any(m in hint for m in _ENV_MARKERS) or category in _INFRA_CATEGORIES:
        if "429" in hint or "rate limit" in hint or "resource_exhausted" in hint:
            return "flaky"
        return "env"
    return "code"


def annotate_qa_issues(qa_report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(qa_report, dict):
        return qa_report
    out = dict(qa_report)
    issues = []
    counts: dict[str, int] = {"code": 0, "env": 0, "flaky": 0, "blocked": 0}
    for issue in qa_report.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        row = dict(issue)
        cls = classify_issue(row)
        row["issue_class"] = cls
        counts[cls] = counts.get(cls, 0) + 1
        issues.append(row)
    out["issues"] = issues
    out["issue_classification"] = counts
    return out


def build_issue_traceability(
    qa_report: dict[str, Any] | None,
    fixes: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Map QA issues to applied/skipped fixes and commits."""
    issues = (qa_report or {}).get("issues") or []
    applied = (fixes or {}).get("fixes_applied") or []
    skipped = (fixes or {}).get("fixes_skipped") or []
    by_index: dict[int, list[dict[str, Any]]] = {}
    for fix in applied:
        if not isinstance(fix, dict):
            continue
        idx = fix.get("qa_issue_index")
        if idx is None:
            continue
        try:
            by_index.setdefault(int(idx), []).append(fix)
        except (TypeError, ValueError):
            continue

    rows: list[dict[str, Any]] = []
    for i, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        matched = by_index.get(i, [])
        skip_for = [
            s
            for s in skipped
            if isinstance(s, dict) and s.get("qa_issue_index") == i
        ]
        commits = [
            str(f.get("commit_hash"))
            for f in matched
            if f.get("commit_hash") and str(f.get("commit_hash")).strip() not in ("", "—")
        ]
        rows.append(
            {
                "qa_issue_index": i,
                "severity": issue.get("severity"),
                "category": issue.get("category"),
                "issue_class": issue.get("issue_class") or classify_issue(issue),
                "description": issue.get("description"),
                "status": "fixed" if matched else ("skipped" if skip_for else "open"),
                "fixes": matched,
                "fixes_skipped": skip_for,
                "commit_hashes": commits,
            }
        )
    return rows


def collect_regression_scenarios(*, exclude_session_id: str | None = None, limit: int = 12) -> list[str]:
    from quality_loop.cycle_store import list_completed_cycles
    from quality_loop.session_store import load_session

    seen: set[str] = set()
    scenarios: list[str] = []
    for row in list_completed_cycles():
        sid = str(row.get("session_id") or row.get("cycle_id") or "")
        if not sid or sid == exclude_session_id:
            continue
        session = load_session(sid)
        if not session:
            continue
        fixes = session.get("fixes") if isinstance(session.get("fixes"), dict) else {}
        for src in (
            fixes.get("next_test_scenarios") or [],
            (fixes.get("cursor_summary") or {}).get("next_test_scenarios") or [],
        ):
            for item in src:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                scenarios.append(text)
                if len(scenarios) >= limit:
                    return scenarios
    return scenarios


def _session_metrics(session: dict[str, Any]) -> dict[str, Any]:
    qa = session.get("qa_report") if isinstance(session.get("qa_report"), dict) else {}
    summary = session.get("summary") if isinstance(session.get("summary"), dict) else {}
    fixes = session.get("fixes") if isinstance(session.get("fixes"), dict) else {}
    applied = [f for f in fixes.get("fixes_applied") or [] if isinstance(f, dict)]
    issue_indices = {
        f.get("qa_issue_index") for f in applied if f.get("qa_issue_index") is not None
    }
    scores = qa.get("scores") or {}
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    avg = round(sum(vals) / len(vals), 1) if vals else summary.get("avg_score")
    return {
        "session_id": session.get("session_id"),
        "created_at": session.get("created_at"),
        "verdict": qa.get("overall_verdict") or summary.get("verdict"),
        "issue_count": len(qa.get("issues") or []) or summary.get("issue_count") or 0,
        "avg_score": avg,
        "fixes_applied": len(applied) or summary.get("fixes_applied") or 0,
        "issues_addressed": len(issue_indices) if issue_indices else len(applied),
        "fixes_committed": sum(
            1
            for f in applied
            if str(f.get("commit_hash") or "").strip() not in ("", "—")
        ),
        "issue_classification": (qa.get("issue_classification") or {}),
    }


def collect_session_trends(*, limit: int = 20) -> dict[str, Any]:
    from quality_loop.cycle_store import list_completed_cycles
    from quality_loop.session_store import load_session

    points: list[dict[str, Any]] = []
    for row in list_completed_cycles()[:limit]:
        sid = str(row.get("session_id") or row.get("cycle_id") or "")
        session = load_session(sid) if sid else None
        if not session:
            continue
        points.append(_session_metrics(session))

    baseline = points[-1] if points else None
    latest = points[0] if points else None
    delta: dict[str, Any] = {}
    if baseline and latest and baseline.get("session_id") != latest.get("session_id"):
        for key in ("issue_count", "avg_score", "fixes_applied", "issues_addressed"):
            b, l = baseline.get(key), latest.get(key)
            if isinstance(b, (int, float)) and isinstance(l, (int, float)):
                delta[key] = round(l - b, 1) if key == "avg_score" else l - b

    return {
        "baseline_session_id": baseline.get("session_id") if baseline else None,
        "latest_session_id": latest.get("session_id") if latest else None,
        "delta_vs_baseline": delta,
        "points": points,
    }


def collect_blocked_backlog(*, limit: int = 40) -> list[dict[str, Any]]:
    from quality_loop.cycle_store import list_completed_cycles
    from quality_loop.session_store import load_session

    backlog: dict[str, dict[str, Any]] = {}
    for row in list_completed_cycles():
        sid = str(row.get("session_id") or "")
        session = load_session(sid) if sid else None
        if not session:
            continue
        created = (session.get("updated_at") or session.get("created_at") or "")[:10]
        qa = session.get("qa_report") if isinstance(session.get("qa_report"), dict) else {}
        for issue in qa.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            cls = issue.get("issue_class") or classify_issue(issue)
            if cls not in ("blocked", "env", "flaky"):
                continue
            key = f"{cls}:{issue.get('category')}:{(issue.get('description') or '')[:80]}"
            entry = backlog.setdefault(
                key,
                {
                    "kind": cls,
                    "category": issue.get("category"),
                    "severity": issue.get("severity"),
                    "description": issue.get("description"),
                    "sessions": [],
                    "occurrences": 0,
                },
            )
            entry["occurrences"] += 1
            if sid not in entry["sessions"]:
                entry["sessions"].append(sid)
            entry["last_seen"] = created

        fixes = session.get("fixes") if isinstance(session.get("fixes"), dict) else {}
        for skip in fixes.get("fixes_skipped") or []:
            if not isinstance(skip, dict):
                continue
            key = f"skip:{skip.get('repo')}:{skip.get('issue') or skip.get('reason')}"
            entry = backlog.setdefault(
                key,
                {
                    "kind": "skipped_fix",
                    "category": skip.get("issue"),
                    "severity": "medium",
                    "description": skip.get("reason") or skip.get("issue"),
                    "sessions": [],
                    "occurrences": 0,
                },
            )
            entry["occurrences"] += 1
            if sid not in entry["sessions"]:
                entry["sessions"].append(sid)
            entry["last_seen"] = created

    rows = sorted(backlog.values(), key=lambda r: (-r["occurrences"], r.get("last_seen") or ""))
    return rows[:limit]


def auto_verify_enabled() -> bool:
    return os.environ.get("QUALITY_LOOP_AUTO_VERIFY", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )
