"""Validate and scrub QA reports so issues reference only the target session."""

from __future__ import annotations

from typing import Any


def sanitize_qa_report(
    qa_report: dict[str, Any] | None,
    *,
    session_id: str,
    message_count: int,
) -> dict[str, Any] | None:
    if not isinstance(qa_report, dict):
        return qa_report

    issues = qa_report.get("issues")
    if not isinstance(issues, list):
        return qa_report

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        idx = issue.get("message_index")
        if idx is None:
            kept.append(issue)
            continue
        try:
            i = int(idx)
        except (TypeError, ValueError):
            dropped.append({**issue, "_drop_reason": "invalid message_index"})
            continue
        if message_count <= 0 or i < 0 or i >= message_count:
            dropped.append(
                {
                    **issue,
                    "_drop_reason": (
                        f"message_index {i} out of range for session {session_id} "
                        f"(0..{max(message_count - 1, 0)})"
                    ),
                }
            )
            continue
        kept.append(issue)

    out = dict(qa_report)
    out["issues"] = kept
    if dropped:
        out["sanitization"] = {
            "session_id": session_id,
            "message_count": message_count,
            "dropped_issue_count": len(dropped),
            "dropped_issues": dropped,
            "note": (
                "Issues removed because message_index did not exist in fetch_conversation "
                "for this session (likely cross-session log contamination)."
            ),
        }
    return out
