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
) -> Path:
    """Write canonical run manifest under outputs/runs/."""
    from quality_loop.fix_snapshots import enrich_fixes

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rid = run_id or new_run_id()
    phases = [_task_output(task, phase=phase, agent=agent) for task, phase, agent in tasks]
    linked_session = session_id or _extract_session_id(phases)
    qa_report = _qa_from_phases(phases)
    fixes = enrich_fixes(
        _fixes_from_phases(phases),
        job_id=job_id or os.environ.get("QUALITY_LOOP_JOB_ID"),
    )
    final_text = str(getattr(final_result, "raw", None) or final_result)

    payload: dict[str, Any] = {
        "run_id": rid,
        "mode": mode,
        "iteration": iteration,
        "created_at": _utcnow_iso(),
        "session_id": linked_session,
        "advisor_url": advisor_url,
        "job_id": job_id or os.environ.get("QUALITY_LOOP_JOB_ID"),
        "phases": phases,
        "qa_report": qa_report,
        "fixes": fixes,
        "final_result": final_text,
        "summary": {
            "verdict": (qa_report or {}).get("overall_verdict") if isinstance(qa_report, dict) else None,
            "issue_count": len((qa_report or {}).get("issues") or []) if isinstance(qa_report, dict) else 0,
            "fixes_applied": len((fixes or {}).get("fixes_applied") or []) if isinstance(fixes, dict) else 0,
            "fixes_skipped": len((fixes or {}).get("fixes_skipped") or []) if isinstance(fixes, dict) else 0,
            "turn_count": (phases[0].get("parsed_output") or {}).get("turn_count")
            if phases and phases[0].get("phase") == "conversation"
            and isinstance(phases[0].get("parsed_output"), dict)
            else None,
        },
    }

    path = RUNS_DIR / f"{rid}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Legacy iteration/analyze files still written by crew.py for backward compatibility.
    return path


def list_runs() -> list[dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = _read_json(path)
            rows.append(
                {
                    "run_id": data.get("run_id") or path.stem,
                    "mode": data.get("mode"),
                    "iteration": data.get("iteration"),
                    "session_id": data.get("session_id"),
                    "created_at": data.get("created_at"),
                    "summary": data.get("summary") or {},
                    "file": path.name,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return rows


def load_run(run_id: str) -> dict[str, Any]:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    path = RUNS_DIR / f"{safe}.json"
    if not path.exists():
        raise FileNotFoundError(run_id)
    return _read_json(path)


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data
