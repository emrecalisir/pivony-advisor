"""Hard agent state: authoritative dashboard / period scope for a single turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.analytics_scope import (
    EstablishedAnalyticsScope,
    infer_established_analytics_scope,
    parse_days_from_text,
    scope_prompt_block,
)


def _int_or_none(value: Any) -> int | None:
    """Parse a dashboard id; treat 0 and negatives as unset (UI placeholder)."""
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_dashboard_id(value: Any) -> int | None:
    """Public helper: parse dashboard id; 0/negative are treated as unset."""
    return _int_or_none(value)


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
    dashboard_name: str | None = None  # Added dashboard_name
    org_wide: bool = False
    since: str | None = None
    until: str | None = None
    days: int | None = None
    dashboard_locked: bool = False
    source: str = "none"

    @property
    def has_dashboard(self) -> bool:
        """True only for positive dashboard ids; 0/negative are UI placeholders."""
        return self.dashboard_id is not None and self.dashboard_id > 0

    @property
    def scope_resolved(self) -> bool:
        return self.has_dashboard or self.org_wide

    @property
    def period_resolved(self) -> bool:
        """True when the user or page supplied an explicit date window."""
        if self.since and self.until:
            return True
        return self.days is not None and self.days > 0

    def dashboard_selection_payload(self) -> dict[str, Any] | None:
        """UI-facing dashboard pick for assistant responses and SSE done events."""
        if self.dashboard_id is None:
            return None
        return {
            "id": self.dashboard_id,
            "name": self.dashboard_name or f"Dashboard {self.dashboard_id}",
        }

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


def _latest_user_text(turns: list[tuple[str, str]]) -> str:
    for role, content in reversed(turns or []):
        if role == "user":
            return content or ""
    return ""


def _days_from_page(pc: dict) -> int | None:
    days = _int_or_none(pc.get("days"))
    if days is not None:
        return days
    days = _int_or_none(pc.get("selectedDaysRange"))
    if days is not None:
        return days
    raw_scope = pc.get("analytics_scope")
    if isinstance(raw_scope, dict):
        days = _int_or_none(raw_scope.get("days"))
        if days is not None:
            return days
    return None


def resolve_hard_agent_state(
    turns: list[tuple[str, str]],
    page_context: dict | None,
) -> HardAgentState:
    """
    Resolve authoritative scope for this turn.

    Priority:
      1. page_context.dashboard_id (UI pin — locked)
      2. _dashboard_from_picker_context (explicit user choice from current or last turn)
      3. page_context.analytics_scope
      4. inferred established scope from prior turns (dates/org-wide only;
         dashboard_id never inferred from model output)
    """
    pc = page_context if isinstance(page_context, dict) else {}
    since_pc, until_pc = _dates_from_page(pc)
    raw_scope_early = pc.get("analytics_scope")
    if isinstance(raw_scope_early, dict):
        if not since_pc and raw_scope_early.get("since"):
            since_pc = str(raw_scope_early.get("since")).strip() or None
        if not until_pc and raw_scope_early.get("until"):
            until_pc = str(raw_scope_early.get("until")).strip() or None
    days_pc = _days_from_page(pc)
    if days_pc is None:
        days_pc = parse_days_from_text(_latest_user_text(turns))

    # Determine explicit dashboard selection from UI (picker or last session) early
    user_explicit_dashboard_id = None
    user_explicit_dashboard_name = None
    user_explicit_dashboard_locked = False
    last_dashboard_selection_id = None
    last_dashboard_selection_name = None
    for key in ("dashboard_selection", "last_dashboard_selection"):
        selection = pc.get(key)
        if isinstance(selection, dict):
            sel_id = _int_or_none(selection.get("id"))
            sel_name = selection.get("name")
            if sel_id is not None:
                if key == "dashboard_selection":
                    user_explicit_dashboard_id = sel_id
                    user_explicit_dashboard_name = str(sel_name) if sel_name else None
                    user_explicit_dashboard_locked = True
                    break
                last_dashboard_selection_id = sel_id
                last_dashboard_selection_name = str(sel_name) if sel_name else None

    if pc.get("fresh_session") is True:
        # Fresh session: honour only an explicit pick on this turn, not stale context.
        if user_explicit_dashboard_id is not None:
            return HardAgentState(
                dashboard_id=user_explicit_dashboard_id,
                dashboard_name=user_explicit_dashboard_name,
                since=since_pc,
                until=until_pc,
                days=days_pc,
                dashboard_locked=user_explicit_dashboard_locked,
                source="dashboard_selection",
            )
        return HardAgentState(
            since=since_pc,
            until=until_pc,
            days=days_pc,
            source="fresh_session",
        )

    # 1. Highest priority: UI pinned dashboard_id (e.g., from URL or persistent UI state)
    locked_dash_from_ui_pin = _int_or_none(pc.get("dashboard_id"))
    if locked_dash_from_ui_pin is not None:
        # Try to get the name from the explicit selection if it matches the pinned ID
        resolved_dashboard_name = (
            user_explicit_dashboard_name
            if user_explicit_dashboard_id == locked_dash_from_ui_pin
            else None
        )
        return HardAgentState(
            dashboard_id=locked_dash_from_ui_pin,
            dashboard_name=resolved_dashboard_name,  # Pass name if available
            since=since_pc,
            until=until_pc,
            days=days_pc,
            dashboard_locked=True,
            source="page_dashboard_id",
        )

    # 2. Next priority: Analytics scope (model-inferred or persistent from backend)
    raw_scope = pc.get("analytics_scope")
    if isinstance(raw_scope, dict):
        scope_dash = _int_or_none(raw_scope.get("dashboard_id"))
        scope_days = _int_or_none(raw_scope.get("days"))
        scope_since = raw_scope.get("since")
        scope_until = raw_scope.get("until")

        if scope_dash is not None:
            resolved_dashboard_name = (
                user_explicit_dashboard_name
                if user_explicit_dashboard_id == scope_dash
                else None
            )
            return HardAgentState(
                dashboard_id=scope_dash,
                dashboard_name=resolved_dashboard_name,
                since=str(scope_since).strip() if scope_since else since_pc,
                until=str(scope_until).strip() if scope_until else until_pc,
                days=scope_days if scope_days is not None else days_pc,
                dashboard_locked=True,
                source="analytics_scope",
            )
        if raw_scope.get("org_wide"):
            deferred_dash_id = user_explicit_dashboard_id or last_dashboard_selection_id
            deferred_dash_name = (
                user_explicit_dashboard_name
                if user_explicit_dashboard_id is not None
                else last_dashboard_selection_name
            )
            if deferred_dash_id is not None:
                deferred_source = (
                    "dashboard_selection"
                    if user_explicit_dashboard_id is not None
                    else "last_dashboard_selection"
                )
                return HardAgentState(
                    dashboard_id=deferred_dash_id,
                    dashboard_name=deferred_dash_name,
                    org_wide=False,
                    since=str(scope_since).strip() if scope_since else since_pc,
                    until=str(scope_until).strip() if scope_until else until_pc,
                    days=scope_days or days_pc,
                    dashboard_locked=True,
                    source=deferred_source,
                )
            return HardAgentState(
                org_wide=True,
                since=str(scope_since).strip() if scope_since else since_pc,
                until=str(scope_until).strip() if scope_until else until_pc,
                days=scope_days or days_pc,
                dashboard_locked=False,
                source="analytics_scope_org_wide",
            )

    # 3. Next priority: User's explicit dashboard selection from picker context
    # This ensures that an explicit user selection persists if not overridden by higher priority sources.
    if user_explicit_dashboard_id is not None:
        return HardAgentState(
            dashboard_id=user_explicit_dashboard_id,
            dashboard_name=user_explicit_dashboard_name,
            since=since_pc,
            until=until_pc,
            days=days_pc,
            dashboard_locked=user_explicit_dashboard_locked,
            source="dashboard_selection",
        )
    if last_dashboard_selection_id is not None:
        return HardAgentState(
            dashboard_id=last_dashboard_selection_id,
            dashboard_name=last_dashboard_selection_name,
            since=since_pc,
            until=until_pc,
            days=days_pc,
            dashboard_locked=True,
            source="last_dashboard_selection",
        )

    # 4. Fallback: Inferred established scope from prior turns
    established = infer_established_analytics_scope(turns, page_context)
    if established is not None:
        if established.org_wide and established.dashboard_id is None:
            deferred_dash = _dashboard_from_picker_context(pc)
            if deferred_dash is not None:
                return HardAgentState(
                    dashboard_id=deferred_dash,
                    org_wide=False,
                    since=established.since or since_pc,
                    until=established.until or until_pc,
                    days=established.days,
                    dashboard_locked=True,
                    source="last_dashboard_selection",
                )
        # No dashboard name available from inferred scope reliably
        return HardAgentState(
            dashboard_id=established.dashboard_id,
            org_wide=established.org_wide,
            since=established.since or since_pc,
            until=established.until or until_pc,
            days=established.days,
            dashboard_locked=False,
            source="established",
        )

    # Default: no dashboard, just time scope if any
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
            f"HARD CONTEXT (authoritative, do not ignore): dashboard_id={state.dashboard_id}"
        ]
        if state.dashboard_name:
            parts[0] += f" (name='{state.dashboard_name}')"
        parts[0] += " is locked for this turn."
        if state.since and state.until:
            parts.append(f"Date window: {state.since} to {state.until}.")
        elif state.days:
            parts.append(f"Look-back: last {state.days} days.")
        else:
            parts.append(
                "Period is NOT set. Do not guess days (not 90, not 'recent' / 'son günlerde'). "
                "Ask in one short sentence which window to use. The UI shows 7/30/90 day chips. "
                "Do not call analysis tools until the user picks a period."
            )
        parts.append(
            "You SHOULD primarily use this locked dashboard for analysis. However, if the user "
            "explicitly asks to list other dashboards or change the current dashboard, "
            "you MAY call list_dashboards to assist them."
        )
        return " ".join(parts)
    if base:
        return f"HARD CONTEXT (authoritative): {base}"
    return ""
