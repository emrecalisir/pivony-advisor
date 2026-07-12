"""Persist structured quality-loop run artifacts for transparent UI inspection."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os

_PACKAGE_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = _PACKAGE_ROOT / "outputs"
RUNS_DIR = OUTPUT_DIR / "runs"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"run_{stamp}_{uuid.uuid4().hex[:8]}"


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _repair_json_text(text: str) -> str:
    # LLMs often emit invalid JSON escapes such as \' inside strings.
    return re.sub(r"(?<!\\)\\'", "'", text)


def try_parse_json(text: str | None) -> Any | None:
    if not text:
        return None
    stripped = _strip_code_fence(str(text))
    candidates = [stripped]
    if stripped.startswith("{") or stripped.startswith("["):
        candidates.insert(0, stripped)
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if match and match.group(1) not in candidates:
        candidates.append(match.group(1))

    for candidate in candidates:
        for attempt in (candidate, _repair_json_text(candidate)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    return None


def _task_output(task: Any, *, phase: str, agent: str) -> dict[str, Any]:
    output = getattr(task, "output", None)
    raw = ""
    parsed: Any | None = None
    if output is not None:
        raw = str(getattr(output, "raw", None) or output)
        parsed = getattr(output, "json_dict", None)
        if parsed is None:
            parsed = try_parse_json(raw)
    return {
        "phase": phase,
        "agent": agent,
        "task_description": (getattr(task, "description", None) or "")[:800],
        "raw_output": raw,
        "parsed_output": parsed,
    }


def _extract_session_id(phases: list[dict[str, Any]]) -> str | None:
    for phase in phases:
        if phase.get("phase") != "conversation":
            continue
        parsed = phase.get("parsed_output")
        if isinstance(parsed, dict) and parsed.get("session_id"):
            return str(parsed["session_id"])
        raw = phase.get("raw_output") or ""
        match = re.search(r"sess_[a-f0-9]+", raw)
        if match:
            return match.group(0)
    return None


def _qa_from_phases(phases: list[dict[str, Any]]) -> dict[str, Any] | None:
    for phase in phases:
        if phase.get("phase") != "qa":
            continue
        parsed = phase.get("parsed_output")
        if isinstance(parsed, dict):
            return parsed
        reparsed = try_parse_json(phase.get("raw_output"))
        if isinstance(reparsed, dict):
            return reparsed
    return None


def _fixes_from_phases(phases: list[dict[str, Any]]) -> dict[str, Any] | None:
    for phase in phases:
        if phase.get("phase") != "coding":
            continue
        parsed = phase.get("parsed_output")
        if isinstance(parsed, dict):
            return parsed
        reparsed = try_parse_json(phase.get("raw_output"))
        if isinstance(reparsed, dict):
            return reparsed
    return None


def _avg_score_from_qa(qa_report: dict[str, Any] | None) -> float | None:
    scores = (qa_report or {}).get("scores") or {}
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def save_run(
    *,
    mode: str,
    tasks: list[tuple[Any, str, str]],
    final_result: Any,
    iteration: int | None = None,
    session_id: str | None = None,
    advisor_url: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    additional_phases: list[dict[str, Any]] | None = None,
) -> Path:
    """Finalize unified cycle manifest (session file); mirror legacy runs/ for compat."""
    from quality_loop.cycle_store import cycle_as_run, finalize_cycle
    from quality_loop.fix_snapshots import enrich_fixes

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    phases = [_task_output(task, phase=phase, agent=agent) for task, phase, agent in tasks]
    if additional_phases:
        phases.extend(additional_phases)
    linked_session = session_id or _extract_session_id(phases)
    if not linked_session:
        raise ValueError("session_id is required to finalize a cycle")
    cid = linked_session
    qa_report = _qa_from_phases(phases)
    from quality_loop.qa_sanitize import sanitize_qa_report
    from quality_loop.session_store import load_session

    session_for_qa = load_session(cid)
    msg_count = len((session_for_qa or {}).get("messages") or [])
    if isinstance(qa_report, dict):
        qa_report = sanitize_qa_report(
            qa_report,
            session_id=cid,
            message_count=msg_count,
        )
    fixes = enrich_fixes(
        _fixes_from_phases(phases),
        job_id=job_id or os.environ.get("QUALITY_LOOP_JOB_ID"),
        qa_report=qa_report if isinstance(qa_report, dict) else None,
    )
    final_text = str(getattr(final_result, "raw", None) or final_result)
    summary = {
        "verdict": (qa_report or {}).get("overall_verdict") if isinstance(qa_report, dict) else None,
        "issue_count": len((qa_report or {}).get("issues") or []) if isinstance(qa_report, dict) else 0,
        "fixes_applied": len((fixes or {}).get("fixes_applied") or []) if isinstance(fixes, dict) else 0,
        "fixes_skipped": len((fixes or {}).get("fixes_skipped") or []) if isinstance(fixes, dict) else 0,
        "avg_score": _avg_score_from_qa(qa_report if isinstance(qa_report, dict) else None),
        "turn_count": (phases[0].get("parsed_output") or {}).get("turn_count")
        if phases and phases[0].get("phase") == "conversation"
        and isinstance(phases[0].get("parsed_output"), dict)
        else None,
    }

    session = finalize_cycle(
        cid,
        {
            "mode": mode,
            "iteration": iteration,
            "job_id": job_id or os.environ.get("QUALITY_LOOP_JOB_ID"),
            "advisor_url": advisor_url,
            "phases": phases,
            "qa_report": qa_report,
            "fixes": fixes,
            "final_result": final_text,
            "summary": summary,
            "status": "done",
        },
    )

    payload = cycle_as_run(session)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in cid)
    path = RUNS_DIR / f"{safe}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return path


def list_runs() -> list[dict[str, Any]]:
    from quality_loop.cycle_store import list_completed_cycles

    unified = list_completed_cycles()
    seen = {row["run_id"] for row in unified}
    if not RUNS_DIR.exists():
        return unified
    for path in sorted(RUNS_DIR.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = _read_json(path)
            rid = data.get("run_id") or path.stem
            if rid in seen:
                continue
            rows_item = {
                "run_id": rid,
                "cycle_id": data.get("cycle_id") or data.get("session_id") or rid,
                "mode": data.get("mode"),
                "iteration": data.get("iteration"),
                "session_id": data.get("session_id") or rid,
                "created_at": data.get("created_at"),
                "summary": data.get("summary") or {},
                "file": path.name,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                .isoformat(timespec="seconds"),
            }
            unified.append(rows_item)
            seen.add(rid)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    unified.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return unified


def load_run(run_id: str) -> dict[str, Any]:
    from quality_loop.cycle_store import cycle_as_run, is_completed_cycle
    from quality_loop.session_store import load_session

    session = load_session(run_id)
    if session and is_completed_cycle(session):
        return cycle_as_run(session)

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    path = RUNS_DIR / f"{safe}.json"
    if path.exists():
        data = _read_json(path)
        linked = data.get("session_id")
        if linked and linked != run_id:
            merged = load_session(str(linked))
            if merged and is_completed_cycle(merged):
                return cycle_as_run(merged)
        return data

    if session:
        return cycle_as_run(session)

    raise FileNotFoundError(run_id)


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data
