"""Established analytics scope across advisor turns (dashboard vs org-wide)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EstablishedAnalyticsScope:
    dashboard_id: int | None = None
    org_wide: bool = False
    days: int | None = None
    since: str | None = None
    until: str | None = None


def _parse_days_from_text(text: str) -> int | None:
    lower = (text or "").lower()
    m = re.search(r"son\s+(\d+)\s+g", lower)
    if m:
        return int(m.group(1))
    m = re.search(r"last\s+(\d+)\s+days?", lower)
    if m:
        return int(m.group(1))
    return None


def assistant_text_has_substantive_data(text: str) -> bool:
    if not text:
        return False
    if re.search(r"\d", text):
        return True
    if "%" in text:
        return True
    if re.search(r"^\s*\d+\.", text, re.MULTILINE):
        return True
    return False


def _scope_from_page_context(page_context: dict | None) -> EstablishedAnalyticsScope | None:
    if not isinstance(page_context, dict):
        return None

    raw = page_context.get("analytics_scope")
    if isinstance(raw, dict):
        dash = raw.get("dashboard_id")
        try:
            dash_id = int(dash) if dash is not None else None
        except (TypeError, ValueError):
            dash_id = None
        days = raw.get("days")
        try:
            days_i = int(days) if days is not None else None
        except (TypeError, ValueError):
            days_i = None
        return EstablishedAnalyticsScope(
            dashboard_id=dash_id,
            org_wide=bool(raw.get("org_wide")) and dash_id is None,
            days=days_i,
            since=raw.get("since") or None,
            until=raw.get("until") or None,
        )

    dash = page_context.get("dashboard_id")
    if dash is not None:
        try:
            return EstablishedAnalyticsScope(dashboard_id=int(dash))
        except (TypeError, ValueError):
            pass

    selection = page_context.get("dashboard_selection")
    if isinstance(selection, dict) and selection.get("id") is not None:
        try:
            return EstablishedAnalyticsScope(dashboard_id=int(selection["id"]))
        except (TypeError, ValueError):
            pass

    return None


def infer_established_analytics_scope(
    turns: list[tuple[str, str]],
    page_context: dict | None,
) -> EstablishedAnalyticsScope | None:
    """
    Return the analytics scope the current turn should inherit.

    Priority: explicit page/analytics_scope → pinned dashboard_id → last
    substantive assistant answer (org-wide fallback).
    """
    from_context = _scope_from_page_context(page_context)
    if from_context and from_context.dashboard_id is not None:
        return from_context

    if not turns:
        return None

    last_substantive: str | None = None
    for role, content in reversed(turns):
        if role != "assistant":
            continue
        text = (content or "").strip()
        if assistant_text_has_substantive_data(text):
            last_substantive = text
            break

    if not last_substantive:
        return None

    pc = page_context if isinstance(page_context, dict) else {}

    page_dash = pc.get("dashboard_id")
    if page_dash is not None:
        try:
            return EstablishedAnalyticsScope(dashboard_id=int(page_dash))
        except (TypeError, ValueError):
            pass

    selection = pc.get("last_dashboard_selection") or pc.get("dashboard_selection")
    if isinstance(selection, dict) and selection.get("id") is not None:
        try:
            return EstablishedAnalyticsScope(dashboard_id=int(selection["id"]))
        except (TypeError, ValueError):
            pass

    since = pc.get("since")
    until = pc.get("until")
    days = _parse_days_from_text(last_substantive) or 7

    return EstablishedAnalyticsScope(
        org_wide=True,
        days=days,
        since=str(since).strip() if since else None,
        until=str(until).strip() if until else None,
    )


def scope_prompt_block(scope: EstablishedAnalyticsScope | None) -> str:
    if scope is None:
        return ""
    if scope.dashboard_id is not None:
        parts = [f"Established analytics scope: dashboard_id={scope.dashboard_id}."]
        if scope.since and scope.until:
            parts.append(f"Date window: {scope.since} to {scope.until}.")
        elif scope.days:
            parts.append(f"Look-back: last {scope.days} days.")
        parts.append(
            "Follow-up questions SHOULD reuse this dashboard and period if relevant. "
            "If the user asks to change or list dashboards, you MAY call list_dashboards."
        )
        return " ".join(parts)
    if scope.org_wide:
        parts = ["Established analytics scope: organization-wide (org_wide=true)."]
        if scope.since and scope.until:
            parts.append(f"Date window: {scope.since} to {scope.until}.")
        elif scope.days:
            parts.append(f"Look-back: last {scope.days} days.")
        parts.append(
            "Follow-up questions MUST call get_pivony_metrics with org_wide=true and the "
            "same period — do NOT call list_dashboards or show dashboard selection again."
        )
        return " ".join(parts)
    return ""
