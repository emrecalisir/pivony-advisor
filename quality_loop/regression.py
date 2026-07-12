"""Regression gate: prior next_test_scenarios → CX checklist + post-fix verification."""

from __future__ import annotations

import json
from typing import Any

from quality_loop.loop_insights import collect_regression_scenarios


def format_regression_checklist(scenarios: list[str]) -> str:
    if not scenarios:
        return "(önceki session'dan regression senaryosu yok)"
    lines = []
    for i, s in enumerate(scenarios, 1):
        lines.append(f"   {i}. [REGRESSION] {s}")
    return "\n".join(lines)


def run_regression_verification(
    session_id: str,
    scenarios: list[str] | None = None,
    *,
    dashboard_id: int | None = None,
    dashboard_name: str | None = None,
    max_scenarios: int = 5,
) -> dict[str, Any]:
    """Run prior test scenarios against advisor; do not advance on turn_incomplete."""
    from quality_loop.tools.advisor_tool import PivonyAdvisorTool

    tool = PivonyAdvisorTool()
    items = (scenarios or collect_regression_scenarios(exclude_session_id=session_id))[:max_scenarios]
    results: list[dict[str, Any]] = []
    failed = 0

    for text in items:
        kwargs: dict[str, Any] = {"session_id": session_id, "message": text}
        if dashboard_id is not None:
            kwargs["dashboard_id"] = dashboard_id
            kwargs["dashboard_name"] = dashboard_name
        raw = tool._run(**kwargs)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"error": raw}
        ok = not data.get("error") and not data.get("turn_incomplete")
        if not ok:
            failed += 1
        results.append(
            {
                "scenario": text,
                "ok": ok,
                "error": data.get("error"),
                "turn_incomplete": data.get("turn_incomplete"),
                "content_preview": (data.get("content") or "")[:200],
                "tool_actions": data.get("tool_actions") or [],
            }
        )

    return {
        "scenarios_tested": len(results),
        "scenarios_failed": failed,
        "scenarios_passed": len(results) - failed,
        "results": results,
        "status": "pass" if results and failed == 0 else ("partial" if results else "skipped"),
    }
