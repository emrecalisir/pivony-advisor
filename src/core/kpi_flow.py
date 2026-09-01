"""KPI creation flow helpers: name resolution and structured picker artifacts."""

from __future__ import annotations

import json
import re
from typing import Any

from core.agent_state import HardAgentState, parse_dashboard_id
from core.chip_capabilities import is_kpi_creation_intent


def normalize_label(value: str) -> str:
    """Lowercase alphanumeric key for fuzzy name matching."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def conversation_in_kpi_creation(
    turns: list[tuple[str, str]],
    page_context: dict | None,
) -> bool:
    """True when the user is creating a new KPI card (not inventory lookup)."""
    pc = page_context if isinstance(page_context, dict) else {}
    if pc.get("page") == "global_executive" or pc.get("is_kpi_page"):
        for role, content in reversed(turns or []):
            if role == "user" and is_kpi_creation_intent(content or ""):
                return True
    for role, content in turns or []:
        if role == "user" and is_kpi_creation_intent(content or ""):
            return True
    return False


def _user_messages_newest_first(turns: list[tuple[str, str]]) -> list[str]:
    out: list[str] = []
    for role, content in reversed(turns or []):
        if role == "user":
            text = (content or "").strip()
            if text:
                out.append(text)
    return out


def match_dashboard_by_name(name: str, dashboards: list[dict]) -> int | None:
    """Resolve dashboard id from a user-provided label."""
    needle = normalize_label(name)
    if not needle or not dashboards:
        return None
    exact: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    for row in dashboards:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        try:
            dash_id = int(row["id"])
        except (TypeError, ValueError):
            continue
        dn = normalize_label(str(row.get("name") or ""))
        if not dn:
            continue
        if dn == needle:
            exact.append((dash_id, dn))
        elif needle in dn or dn in needle:
            partial.append((dash_id, dn))
    if len(exact) == 1:
        return exact[0][0]
    if len(exact) > 1:
        return None
    if len(partial) == 1:
        return partial[0][0]
    return None


def resolve_dashboard_from_conversation(
    user_id: str | None,
    turns: list[tuple[str, str]],
    page_context: dict | None,
    hard: HardAgentState | None = None,
) -> tuple[int | None, str | None]:
    """
    Resolve dashboard id from hard state, page context picks, or user prose.
    Returns (dashboard_id, dashboard_name).
    """
    if hard and hard.has_dashboard:
        return hard.dashboard_id, hard.dashboard_name

    pc = page_context if isinstance(page_context, dict) else {}
    for key in ("dashboard_selection", "last_dashboard_selection"):
        selection = pc.get(key)
        if isinstance(selection, dict):
            sel_id = parse_dashboard_id(selection.get("id"))
            if sel_id is not None:
                sel_name = selection.get("name")
                return sel_id, str(sel_name) if sel_name else None

    pinned = parse_dashboard_id(pc.get("dashboard_id"))
    if pinned is not None:
        return pinned, pc.get("dashboard_name") or pc.get("dashboardName")

    raw_scope = pc.get("analytics_scope")
    if isinstance(raw_scope, dict):
        scope_id = parse_dashboard_id(raw_scope.get("dashboard_id"))
        if scope_id is not None:
            return scope_id, None

    if not user_id:
        return None, None

    from core.pivony_platform import fetch_dashboards

    payload = fetch_dashboards(user_id)
    dashboards = payload.get("dashboards") if isinstance(payload, dict) else None
    if not isinstance(dashboards, list) or not dashboards:
        return None, None

    for text in _user_messages_newest_first(turns):
        if is_kpi_creation_intent(text):
            continue
        matched = match_dashboard_by_name(text, dashboards)
        if matched is not None:
            name = next(
                (
                    str(d.get("name"))
                    for d in dashboards
                    if isinstance(d, dict) and int(d.get("id")) == matched
                ),
                None,
            )
            return matched, name
    return None, None


def match_kpi_team_by_name(name: str, teams: list[dict]) -> str | None:
    needle = normalize_label(name)
    if not needle or not teams:
        return None
    exact: list[str] = []
    partial: list[str] = []
    for row in teams:
        if not isinstance(row, dict):
            continue
        team_id = row.get("team_id")
        if team_id in (None, ""):
            continue
        tn = normalize_label(str(row.get("team_name") or ""))
        if not tn:
            continue
        tid = str(team_id)
        if tn == needle:
            exact.append(tid)
        elif needle in tn or tn in needle:
            partial.append(tid)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    if len(partial) == 1:
        return partial[0]
    return None


def resolve_kpi_team_from_conversation(
    user_id: str | None,
    turns: list[tuple[str, str]],
    page_context: dict | None,
) -> str | None:
    pc = page_context if isinstance(page_context, dict) else {}
    pinned = (pc.get("kpiTeamId") or pc.get("kpi_team_id") or "").strip()
    if pinned:
        return pinned

    from core.pivony_platform import fetch_kpi_teams

    payload = fetch_kpi_teams(user_id) if user_id else None
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list) or not teams:
        return None

    default_team = (
        payload.get("default_team_id") if isinstance(payload, dict) else None
    )
    if len(teams) == 1:
        only = teams[0].get("team_id") if isinstance(teams[0], dict) else None
        if only not in (None, ""):
            return str(only)

    for text in _user_messages_newest_first(turns):
        if is_kpi_creation_intent(text):
            continue
        matched = match_kpi_team_by_name(text, teams)
        if matched:
            return matched

    if default_team not in (None, ""):
        return str(default_team)
    return None


def build_kpi_team_picker(data: dict) -> dict | None:
    teams_raw = data.get("teams")
    if not isinstance(teams_raw, list):
        return None
    teams = []
    for row in teams_raw:
        if not isinstance(row, dict):
            continue
        team_id = row.get("team_id")
        if team_id in (None, ""):
            continue
        teams.append(
            {
                "team_id": str(team_id),
                "name": str(row.get("team_name") or team_id),
            }
        )
    if len(teams) < 2:
        return None
    return {"teams": teams}


def build_kpi_metric_picker(
    data: dict,
    dashboard_id: int,
    dashboard_name: str | None = None,
) -> dict | None:
    """Flat metric list for KPI creation chips."""
    success = data.get("success")
    block = success if isinstance(success, dict) else data
    if not isinstance(block, dict):
        return None

    metrics: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(label: str, kind: str) -> None:
        key = normalize_label(label)
        if not key or key in seen:
            return
        seen.add(key)
        metrics.append({"label": label, "kind": kind})

    for label in block.get("custom_metrics") or []:
        if label:
            _add(str(label), "topic")
    for label in block.get("general_metrics") or []:
        if label:
            _add(str(label), "general")
    for row in block.get("ai_topics") or []:
        if isinstance(row, dict) and row.get("topic_name"):
            _add(str(row["topic_name"]), "ai_topic")

    if not metrics:
        return None
    return {
        "metrics": metrics,
        "dashboard_id": dashboard_id,
        "dashboard_name": dashboard_name,
    }


def enrich_kpi_metric_list_response(
    data: dict,
    dashboard_id: int,
    dashboard_name: str | None,
) -> dict:
    """Add need_metric_selection + metrics[] for UI pickers."""
    picker = build_kpi_metric_picker(data, dashboard_id, dashboard_name)
    if not picker:
        return data
    return {
        **data,
        "need_metric_selection": True,
        "metrics": picker["metrics"],
        "dashboard_id": dashboard_id,
        "dashboard_name": dashboard_name,
    }


def enrich_kpi_teams_response(
    data: dict,
    resolved_team_id: str | None,
) -> dict:
    if resolved_team_id:
        return data
    picker = build_kpi_team_picker(data)
    if not picker:
        return data
    return {**data, "need_team_selection": True, "teams": picker["teams"]}


def extract_kpi_metric_picker(
    tool_name: str,
    result: Any,
    dashboard_id: int | None,
    dashboard_name: str | None,
) -> dict | None:
    if tool_name != "get_kpi_metric_list" or dashboard_id is None:
        return None
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        return None
    if not data.get("need_metric_selection") and not data.get("success"):
        enriched = enrich_kpi_metric_list_response(data, dashboard_id, dashboard_name)
        return build_kpi_metric_picker(enriched, dashboard_id, dashboard_name)
    return build_kpi_metric_picker(data, dashboard_id, dashboard_name)


def extract_kpi_team_picker(tool_name: str, result: Any) -> dict | None:
    if tool_name != "list_kpi_teams":
        return None
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    if data.get("need_team_selection"):
        teams = data.get("teams")
        if isinstance(teams, list) and len(teams) >= 2:
            return {"teams": teams}
    return build_kpi_team_picker(data)


def should_suppress_dashboard_picker(
    *,
    kpi_creation: bool,
    hard: HardAgentState,
    turns: list[tuple[str, str]],
    page_context: dict | None,
    user_id: str | None,
    tools_called: set[str],
) -> bool:
    """Skip duplicate dashboard pickers during KPI creation."""
    if not kpi_creation:
        return False
    if hard.has_dashboard:
        return True
    if "get_kpi_metric_list" in tools_called:
        return True
    resolved_id, _ = resolve_dashboard_from_conversation(
        user_id, turns, page_context, hard
    )
    return resolved_id is not None


def kpi_creation_prompt_block(
    *,
    kpi_creation: bool,
    hard: HardAgentState,
    page_context: dict | None,
    turns: list[tuple[str, str]],
    user_id: str | None,
) -> str:
    if not kpi_creation:
        return ""
    parts = [
        "KPI CREATION FLOW (mandatory — never ask open-ended for team, dashboard, or metrics):",
        "1. list_kpi_teams() — UI shows team chips when multiple boards exist.",
        "2. list_dashboards() — UI shows dashboard picker ONCE; one short sentence only.",
        "3. get_kpi_metric_list() — UI shows metric chips; NEVER ask 'hangi konular' in prose.",
        "4. Optional get_dashboard_pivots for hotel filter; summarize; create_kpi_view_metric(confirmed=true).",
        "Do NOT repeat list_dashboards after the user picked or named a dashboard.",
    ]
    resolved_id, resolved_name = resolve_dashboard_from_conversation(
        user_id, turns, page_context, hard
    )
    if resolved_id is not None:
        label = resolved_name or f"Dashboard {resolved_id}"
        parts.append(
            f"Dashboard resolved for KPI creation: id={resolved_id} ({label}). "
            "Call get_kpi_metric_list now — do NOT call list_dashboards again."
        )
    team_id = resolve_kpi_team_from_conversation(user_id, turns, page_context)
    if team_id:
        parts.append(f"KPI team resolved: team_id={team_id}.")
    return " ".join(parts)
