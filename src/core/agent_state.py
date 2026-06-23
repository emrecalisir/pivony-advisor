"""Hard agent state: authoritative dashboard / period scope for a single turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.analytics_scope import (
    EstablishedAnalyticsScope,
    infer_established_analytics_scope,
    scope_prompt_block,
)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dashboard_from_picker_context(pc: dict) -> int | None:
    """Latest explicit dashboard pick from UI (current turn or session history)."""
    for key in ("dashboard_selection", "last_dashboard_selection"):
        selection = pc.get(key)
        if isinstance(selection, dict):
            sel_id = _int_or_none(selection.get("id"))
            if sel_id is not None:
                return sel_id
    return None


@dataclass(frozen=True)
class HardAgentState:
    """Resolved analytics scope for tool routing and prompt injection."""

    dashboard_id: int | None = None
    org_wide: bool = False
    since: str | None = None
    until: str | None = None
    days: int | None = None
    dashboard_locked: bool = False
    source: str = "none"

    @property
    def has_dashboard(self) -> bool:
        return self.dashboard_id is not None

    @property
    def scope_resolved(self) -> bool:
        return self.has_dashboard or self.org_wide

    def as_established(self) -> EstablishedAnalyticsScope | None:
        if not self.scope_resolved and self.days is None and not (self.since and self.until):
            return None
        return EstablishedAnalyticsScope(
            dashboard_id=self.dashboard_id,
            org_wide=self.org_wide and not self.has_dashboard,
            days=self.days,
            since=self.since,
            until=self.until,
        )


def _dates_from_page(pc: dict) -> tuple[str | None, str | None]:
    since = pc.get("since")
    until = pc.get("until")
    return (
        str(since).strip() if since else None,
        str(until).strip() if until else None,
    )


def resolve_hard_agent_state(
    turns: list[tuple[str, str]],
    page_context: dict | None,
) -> HardAgentState:
    """
    Resolve authoritative scope for this turn.

    Priority:
      1. page_context.dashboard_id (UI pin — locked)
      2. page_context.dashboard_selection (picker / explicit user choice)
      3. page_context.analytics_scope
      4. inferred established scope from prior turns (dates/org-wide only;
         dashboard_id never inferred from model output)
    """
    pc = page_context if isinstance(page_context, dict) else {}
    since_pc, until_pc = _dates_from_page(pc)
    days_pc = _int_or_none(pc.get("days"))
    if days_pc is None:
        days_pc = _int_or_none(pc.get("selectedDaysRange"))

    if pc.get("fresh_session") is True:
        selection = pc.get("dashboard_selection")
        if isinstance(selection, dict):
            sel_id = _int_or_none(selection.get("id"))
            if sel_id is not None:
                return HardAgentState(
                    dashboard_id=sel_id,
                    since=since_pc,
                    until=until_pc,
                    days=days_pc,
                    dashboard_locked=True,
                    source="dashboard_selection",
                )
        return HardAgentState(
            since=since_pc,
            until=until_pc,
            days=days_pc,
            source="fresh_session",
        )

    raw_scope = pc.get("analytics_scope")
    if isinstance(raw_scope, dict):
        scope_dash = _int_or_none(raw_scope.get("dashboard_id"))
        scope_days = _int_or_none(raw_scope.get("days"))
        scope_since = raw_scope.get("since")
        scope_until = raw_scope.get("until")
        if scope_dash is not None:
            return HardAgentState(
                dashboard_id=scope_dash,
                since=str(scope_since).strip() if scope_since else since_pc,
                until=str(scope_until).strip() if scope_until else until_pc,
                days=scope_days if scope_days is not None else days_pc,
                dashboard_locked=True,
                source="analytics_scope",
            )
        if raw_scope.get("org_wide"):
            picker_dash = _dashboard_from_picker_context(pc)
            if picker_dash is not None:
                return HardAgentState(
                    dashboard_id=picker_dash,
                    since=str(scope_since).strip() if scope_since else since_pc,
                    until=str(scope_until).strip() if scope_until else until_pc,
                    days=scope_days or days_pc or 7,
                    dashboard_locked=True,
                    source="last_dashboard_selection",
                )
            return HardAgentState(
                org_wide=True,
                since=str(scope_since).strip() if scope_since else since_pc,
                until=str(scope_until).strip() if scope_until else until_pc,
                days=scope_days or 7,
                source="analytics_scope",
            )

    locked_dash = _int_or_none(pc.get("dashboard_id"))
    if locked_dash is not None:
        return HardAgentState(
            dashboard_id=locked_dash,
            since=since_pc,
            until=until_pc,
            days=days_pc,
            dashboard_locked=True,
            source="page_dashboard_id",
        )

    selection = pc.get("dashboard_selection")
    if isinstance(selection, dict):
        sel_id = _int_or_none(selection.get("id"))
        if sel_id is not None:
            return HardAgentState(
                dashboard_id=sel_id,
                since=since_pc,
                until=until_pc,
                days=days_pc,
                dashboard_locked=True,
                source="dashboard_selection",
            )

    established = infer_established_analytics_scope(turns, page_context)
    if established is not None:
        return HardAgentState(
            dashboard_id=established.dashboard_id,
            org_wide=established.org_wide,
            since=established.since or since_pc,
            until=established.until or until_pc,
            days=established.days,
            dashboard_locked=established.dashboard_id is not None,
            source="established",
        )

    return HardAgentState(since=since_pc, until=until_pc, days=days_pc, source="none")


def hard_context_prompt_block(state: HardAgentState) -> str:
    """Stronger than scope_prompt_block — marks hard inputs the model must not override."""
    if state.source == "fresh_session":
        return (
            "HARD CONTEXT (authoritative): This is a brand-new chat session with no "
            "prior dashboard, topic, or analytics scope. Do NOT reuse context from "
            "earlier sessions. If the user asks a data question, call list_dashboards "
            "first unless they pick a dashboard in this turn."
        )
    base = scope_prompt_block(state.as_established())
    if state.dashboard_locked and state.dashboard_id is not None:
        parts = [
            f"HARD CONTEXT (authoritative, do not ignore): dashboard_id={state.dashboard_id} "
            "is locked for this turn.",
        ]
        if state.since and state.until:
            parts.append(f"Date window: {state.since} to {state.until}.")
        elif state.days:
            parts.append(f"Look-back: last {state.days} days.")
        parts.append(
            "Do NOT call list_dashboards. Do NOT ask the user to pick a dashboard again. "
            "Proceed directly with get_pivony_metrics and other analysis tools "
            "(dashboard_id is injected server-side from the user's selection)."
        )
        return " ".join(parts)
    if base:
        return f"HARD CONTEXT (authoritative): {base}"
    return ""
