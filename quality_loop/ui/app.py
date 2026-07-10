"""FastAPI dashboard for transparent quality-loop inspection."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quality_loop.architecture import get_architecture
from quality_loop.langsmith_tracing import langsmith_ui_url, observability_status
from quality_loop.prompt_config import list_prompts_meta, read_prompt, write_prompt
from quality_loop.repo_scope import read_scope, scope_summary, write_scope
from quality_loop.vertex_resilience import resilience_status
from quality_loop.fix_snapshots import enrich_fixes
from quality_loop.run_manager import get_active_job, load_job, start_analyze, start_full_loop, stop_job
from quality_loop.run_store import RUNS_DIR, list_runs, load_run, try_parse_json
from quality_loop.ui.auth import (
    auth_required,
    clear_session_cookie,
    request_authenticated,
    set_session_cookie,
)
from quality_loop.ui.export_builder import (
    build_conversation_export_markdown,
    build_qa_export_json,
    export_filename,
    export_payload_from_session_detail,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = _PACKAGE_ROOT / "outputs"
SESSIONS_DIR = OUTPUT_DIR / "sessions"
STATIC_DIR = Path(__file__).resolve().parent / "static"
_UI_TOKEN = os.environ.get("QUALITY_LOOP_UI_TOKEN", "").strip()
_SPA_VIEWS = frozenset({"feedback", "architecture", "runs", "sessions", "qa", "improvements"})

app = FastAPI(title="Pivony Quality Loop UI", version="2.0.0")

if os.environ.get("QUALITY_LOOP_UI_CORS", "true").lower() in ("1", "true", "yes"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _app_relative_path(path: str) -> str:
    """Strip advisor mount prefix so token guard works at /quality-loop and standalone /."""
    for prefix in ("/quality-loop",):
        if path == prefix or path.startswith(prefix + "/"):
            rest = path[len(prefix) :] or "/"
            return rest if rest.startswith("/") else f"/{rest}"
    return path


def _is_public_asset(path: str) -> bool:
    """Allow SPA shell + static assets + auth endpoints without session."""
    rel = _app_relative_path(path)
    if rel in ("/", ""):
        return True
    if rel.startswith("/static") or "/static/" in path:
        return True
    if rel.startswith("/api/auth/"):
        return True
    view = rel.strip("/").split("/")[0] if rel.strip("/") else ""
    if view in _SPA_VIEWS:
        return True
    return rel.endswith((".css", ".js", ".ico", ".png", ".svg", ".woff2"))


@app.middleware("http")
async def optional_token_guard(request: Request, call_next):
    if not auth_required():
        return await call_next(request)
    path = request.url.path
    if _is_public_asset(path):
        return await call_next(request)
    if request_authenticated(request):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "login required"})


def _file_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _list_output_files(prefix: str) -> list[dict[str, Any]]:
    if not OUTPUT_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows.append(
            {
                "name": path.name,
                "modified_at": _file_mtime(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return rows


def _avg_score_from_qa(qa_report: dict[str, Any] | None) -> float | None:
    scores = (qa_report or {}).get("scores") or {}
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _quick_warning_count(messages: list[dict[str, Any]]) -> int:
    warnings = 0
    last_dashboard_id = None
    for msg in messages:
        if msg.get("role") != "assistant":
            dash_sel = msg.get("dashboardSelection")
            if isinstance(dash_sel, dict) and dash_sel.get("id") is not None:
                last_dashboard_id = dash_sel.get("id")
            continue
        tools = msg.get("toolActions") or []
        if last_dashboard_id and any(
            "org_wide" in str(t).lower() or "orgwide" in str(t).lower() for t in tools
        ):
            warnings += 1
        if not (msg.get("content") or "").strip():
            warnings += 1
    return warnings


def _session_performance(session_id: str) -> dict[str, Any]:
    latest = _latest_run_for_session(session_id)
    if not latest:
        return {
            "run_id": None,
            "qa_verdict": None,
            "issue_count": 0,
            "avg_score": None,
            "has_qa": False,
        }
    qa = latest.get("qa_report") if isinstance(latest.get("qa_report"), dict) else {}
    summary = latest.get("summary") or {}
    avg = summary.get("avg_score")
    if avg is None:
        avg = _avg_score_from_qa(qa)
    return {
        "run_id": latest.get("run_id"),
        "qa_verdict": qa.get("overall_verdict"),
        "issue_count": len(qa.get("issues") or []) or summary.get("issue_count") or 0,
        "avg_score": avg,
        "has_qa": bool(qa.get("overall_verdict") or qa.get("issues")),
    }


def _session_status(
    session_id: str,
    turn_count: int,
    *,
    active_job: dict[str, Any] | None,
    live_session_id: str | None,
    has_qa: bool,
) -> dict[str, Any]:
    job_active = bool(active_job and active_job.get("status") in ("queued", "running"))
    phase = (active_job or {}).get("phase") or ""
    job_sid = (active_job or {}).get("session_id")

    if job_active and (
        job_sid == session_id
        or live_session_id == session_id
        or (turn_count == 0 and live_session_id == session_id)
    ):
        return {
            "status": "ongoing",
            "status_label": "Devam ediyor",
            "job_phase": phase,
        }
    if has_qa:
        return {"status": "completed", "status_label": "Bitti", "job_phase": None}
    if turn_count > 0:
        return {"status": "conversation_only", "status_label": "QA yok", "job_phase": None}
    return {"status": "empty", "status_label": "Boş", "job_phase": None}


def _session_summary(
    path: Path,
    *,
    active_job: dict[str, Any] | None = None,
    live_session_id: str | None = None,
) -> dict[str, Any]:
    data = _read_json(path)
    messages = data.get("messages") or []
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    tool_count = sum(len(m.get("toolActions") or []) for m in messages if m.get("role") == "assistant")
    preview = ""
    for msg in messages:
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            preview = str(msg["content"]).strip().replace("\n", " ")[:120]
            break
    session_id = data.get("session_id") or path.stem
    perf = _session_performance(session_id)
    status = _session_status(
        session_id,
        user_turns,
        active_job=active_job,
        live_session_id=live_session_id,
        has_qa=perf["has_qa"],
    )
    return {
        "session_id": session_id,
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "user_id": data.get("user_id"),
        "user_email": data.get("user_email"),
        "turn_count": user_turns,
        "message_count": len(messages),
        "tool_action_count": tool_count,
        "warning_count": _quick_warning_count(messages),
        "sector": data.get("sector"),
        "advisor_mode": data.get("advisor_mode"),
        "preview": preview,
        "file": path.name,
        "modified_at": _file_mtime(path),
        "run_id": perf["run_id"],
        "qa_verdict": perf["qa_verdict"],
        "issue_count": perf["issue_count"],
        "avg_score": perf["avg_score"],
        **status,
    }


def _build_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    turn_no = 0
    pending_user: dict[str, Any] | None = None
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            if pending_user is not None:
                turn_no += 1
                turns.append({"turn": turn_no, "user": pending_user, "assistant": None})
            pending_user = msg
        elif role == "assistant" and pending_user is not None:
            turn_no += 1
            turns.append({"turn": turn_no, "user": pending_user, "assistant": msg})
            pending_user = None
    if pending_user is not None:
        turn_no += 1
        turns.append({"turn": turn_no, "user": pending_user, "assistant": None})
    return turns


def _auto_issues(turns: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    last_dashboard_id = None
    for turn in turns:
        user = turn.get("user") or {}
        assistant = turn.get("assistant") or {}
        dash_sel = user.get("dashboardSelection")
        if isinstance(dash_sel, dict) and dash_sel.get("id") is not None:
            last_dashboard_id = dash_sel.get("id")
        tools = assistant.get("toolActions") or []
        if last_dashboard_id and any("org_wide" in str(t).lower() or "orgwide" in str(t).lower() for t in tools):
            issues.append(f"Turn {turn['turn']}: org_wide tool after dashboard {last_dashboard_id}")
        if assistant and not (assistant.get("content") or "").strip():
            issues.append(f"Turn {turn['turn']}: empty assistant response")
    return issues


def _message_indexes(message_index: Any) -> list[int]:
    if message_index is None:
        return []
    if isinstance(message_index, list):
        out: list[int] = []
        for item in message_index:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return [int(message_index)]
    except (TypeError, ValueError):
        return []


def _issue_matches_turn(message_index: Any, turn: int) -> bool:
    for idx in _message_indexes(message_index):
        if idx // 2 + 1 == turn or idx + 1 == turn:
            return True
    return False


def _issues_for_turn(issues: list[dict[str, Any]], turn: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for issue in issues:
        if _issue_matches_turn(issue.get("message_index"), turn):
            out.append(issue)
    return out


def _attach_qa_to_turns(
    turns: list[dict[str, Any]], qa_report: dict[str, Any] | None
) -> None:
    if not qa_report:
        return
    qa_issues = qa_report.get("issues") or []
    if not qa_issues:
        return
    for turn in turns:
        turn["qa_issues"] = _issues_for_turn(qa_issues, turn["turn"])


def _latest_run_for_session(session_id: str) -> dict[str, Any] | None:
    linked = [r for r in list_runs() if r.get("session_id") == session_id]
    if not linked:
        return None
    linked.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    run_id = linked[0].get("run_id")
    if not run_id:
        return None
    try:
        return load_run(str(run_id))
    except FileNotFoundError:
        return None


def _normalize_run_id_param(run_id: str | None, job_id: str | None) -> str | None:
    if run_id and str(run_id).strip():
        return str(run_id).strip()
    if job_id and str(job_id).startswith("run_"):
        return str(job_id).strip()
    return None


def _run_for_session_export(
    session_id: str,
    *,
    run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any] | None:
    candidate = _normalize_run_id_param(run_id, job_id)
    if candidate:
        try:
            run = load_run(candidate)
        except FileNotFoundError:
            return _latest_run_for_session(session_id)
        if run.get("session_id") == session_id:
            return run
        return _latest_run_for_session(session_id)
    return _latest_run_for_session(session_id)


def _qa_export_meta_from_run(run: dict[str, Any]) -> dict[str, Any]:
    session_detail = run.get("session_detail") if isinstance(run.get("session_detail"), dict) else {}
    fixes = enrich_fixes(
        run.get("fixes") if isinstance(run.get("fixes"), dict) else None,
        job_id=run.get("job_id"),
        qa_report=run.get("qa_report") if isinstance(run.get("qa_report"), dict) else None,
    )
    return {
        "session_id": run.get("session_id"),
        "sector": session_detail.get("sector"),
        "user_email": session_detail.get("user_email"),
        "user_id": session_detail.get("user_id"),
        "run_id": run.get("run_id"),
        "job_id": run.get("job_id"),
        "turn_count": len(session_detail.get("turns") or []),
        "qa_report": run.get("qa_report"),
        "fixes": fixes,
        "summary": run.get("summary"),
    }


def _qa_export_meta_from_session_detail(
    detail: dict[str, Any],
    *,
    run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    session_id = str(detail.get("session_id") or "")
    run = _run_for_session_export(session_id, run_id=run_id, job_id=job_id)
    if run:
        return _qa_export_meta_from_run(run)
    return {
        "session_id": session_id,
        "sector": detail.get("sector"),
        "user_email": detail.get("user_email"),
        "user_id": detail.get("user_id"),
        "run_id": detail.get("run_id"),
        "job_id": job_id,
        "turn_count": detail.get("turn_count"),
        "qa_report": detail.get("qa_report"),
        "fixes": None,
        "summary": None,
    }


class StartJobRequest(BaseModel):
    mode: Literal["full", "analyze"] = "full"
    iterations: int = Field(default=1, ge=1, le=5)
    session_id: str | None = None
    sector: str | None = None


class SavePromptRequest(BaseModel):
    content: str = Field(min_length=1)


class SaveRepoScopeRequest(BaseModel):
    write_repo: str = Field(min_length=1)
    read_repos: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


@app.get("/api/auth/status")
def api_auth_status(request: Request) -> dict[str, Any]:
    return {
        "auth_required": auth_required(),
        "authenticated": request_authenticated(request),
    }


@app.post("/api/auth/login")
def api_auth_login(request: Request, body: LoginRequest) -> Response:
    if not auth_required():
        return JSONResponse({"authenticated": True, "auth_required": False})
    if body.password != _UI_TOKEN:
        raise HTTPException(status_code=401, detail="invalid password")
    response = JSONResponse({"authenticated": True, "auth_required": True})
    set_session_cookie(response, request)
    return response


@app.post("/api/auth/logout")
def api_auth_logout(request: Request) -> Response:
    response = JSONResponse({"authenticated": False, "auth_required": auth_required()})
    clear_session_cookie(response, request)
    return response


def _job_live_payload(job: dict[str, Any]) -> dict[str, Any]:
    session_id = _best_live_session_id(job)
    session_detail = None
    qa_preview = None
    obs = observability_status()
    if session_id:
        try:
            session_detail = get_session(session_id)  # type: ignore[assignment]
        except HTTPException:
            session_detail = None
    run_id = job.get("run_id")
    if run_id:
        try:
            run = load_run(str(run_id))
            qa_preview = {
                "verdict": (run.get("qa_report") or {}).get("overall_verdict"),
                "priority_fix": (run.get("qa_report") or {}).get("priority_fix"),
                "issues": (run.get("qa_report") or {}).get("issues") or [],
                "scores": (run.get("qa_report") or {}).get("scores"),
            }
        except FileNotFoundError:
            qa_preview = None
    return {
        **job,
        "turn_count": _session_turn_count_live(session_id),
        "session_detail": session_detail,
        "qa_preview": qa_preview,
        "observability": obs,
        "vertex_resilience": resilience_status(),
        "langsmith_url": langsmith_ui_url() if obs.get("enabled") else None,
        "flow": [
            {
                "step": 1,
                "id": "conversation",
                "agent": "CX Director",
                "title": "Konuşma testi",
                "desc": "Gerçekçi senaryolarla Advisor'ı zorlar",
                "active": job.get("phase") == "conversation",
                "done": job.get("phase") in ("qa", "coding", "done"),
            },
            {
                "step": 2,
                "id": "qa",
                "agent": "QA Agent (Quality Checker)",
                "title": "Kalite kararı",
                "desc": "Hangi noktada Advisor gelişmeli — kararı QA verir",
                "active": job.get("phase") == "qa",
                "done": job.get("phase") in ("coding", "done"),
            },
            {
                "step": 3,
                "id": "coding",
                "agent": "Coding Agent",
                "title": "İyileştirme",
                "desc": "QA raporundaki fix_hint'lere göre kod düzeltir",
                "active": job.get("phase") == "coding",
                "done": job.get("phase") == "done",
            },
        ],
    }


def _best_live_session_id(job: dict[str, Any]) -> str | None:
    session_id = job.get("session_id")
    if session_id and _session_turn_count_live(session_id) > 0:
        return session_id
    if job.get("status") not in ("queued", "running") or not SESSIONS_DIR.exists():
        return session_id
    best_id: str | None = None
    best_turns = 0
    best_mtime = 0.0
    started = job.get("started_at") or ""
    for path in SESSIONS_DIR.glob("sess_*.json"):
        try:
            data = _read_json(path)
            turns = sum(1 for m in data.get("messages") or [] if m.get("role") == "user")
            if turns <= best_turns:
                continue
            updated = data.get("updated_at") or ""
            if started and updated and updated < started:
                continue
            mtime = path.stat().st_mtime
            if turns > best_turns or mtime > best_mtime:
                best_turns = turns
                best_mtime = mtime
                best_id = data.get("session_id") or path.stem
        except (json.JSONDecodeError, ValueError, OSError):
            continue
    return best_id or session_id


def _session_turn_count_live(session_id: str | None) -> int:
    if not session_id:
        return 0
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    path = SESSIONS_DIR / f"{safe}.json"
    if not path.exists():
        return 0
    try:
        data = _read_json(path)
        return sum(1 for m in data.get("messages") or [] if m.get("role") == "user")
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "output_dir": str(OUTPUT_DIR),
        "runs_dir": str(RUNS_DIR),
        "auth_required": bool(_UI_TOKEN),
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    runs = list_runs()
    sessions: list[dict[str, Any]] = []
    if SESSIONS_DIR.exists():
        active_job = get_active_job()
        live_session_id = _best_live_session_id(active_job) if active_job else None
        for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                sessions.append(
                    _session_summary(
                        path,
                        active_job=active_job,
                        live_session_id=live_session_id,
                    )
                )
            except (json.JSONDecodeError, ValueError, OSError):
                continue

    ongoing_sessions = sum(1 for s in sessions if s.get("status") == "ongoing")
    total_issues = sum((r.get("summary") or {}).get("issue_count", 0) for r in runs)
    total_fixes = sum((r.get("summary") or {}).get("fixes_applied", 0) for r in runs)

    return {
        "output_dir": str(OUTPUT_DIR),
        "counts": {
            "runs": len(runs),
            "sessions": len(sessions),
            "ongoing_sessions": ongoing_sessions,
            "iterations": len(_list_output_files("iteration_")),
            "analyze_runs": len(_list_output_files("analyze_")),
            "total_issues": total_issues,
            "total_fixes_applied": total_fixes,
        },
        "latest_run": runs[0] if runs else None,
        "latest_session": sessions[0] if sessions else None,
        "advisor_url": os.environ.get("PIVONY_ADVISOR_URL", "http://127.0.0.1:8000"),
    }


@app.get("/api/runs")
def api_list_runs() -> list[dict[str, Any]]:
    return list_runs()


@app.get("/api/jobs/active")
def api_active_job() -> dict[str, Any] | None:
    job = get_active_job()
    if not job:
        return None
    return _job_live_payload(job)


@app.post("/api/jobs/start")
def api_start_job(body: StartJobRequest) -> dict[str, Any]:
    try:
        if body.mode == "analyze":
            if not body.session_id:
                raise HTTPException(status_code=400, detail="session_id required for analyze")
            job = start_analyze(body.session_id)
        else:
            job = start_full_loop(iterations=body.iterations, sector=body.sector)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _job_live_payload(job)


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict[str, Any]:
    try:
        job = load_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return _job_live_payload(job)


@app.post("/api/jobs/stop")
def api_stop_job() -> dict[str, Any]:
    try:
        job = stop_job()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_live_payload(job)


@app.get("/api/observability")
def api_observability() -> dict[str, Any]:
    return observability_status()


@app.get("/api/architecture")
def api_architecture() -> dict[str, Any]:
    arch = get_architecture()
    arch["observability_live"] = observability_status()
    arch["prompts"] = list_prompts_meta()
    arch["repo_scope"] = scope_summary()
    return arch


@app.get("/api/repos")
def api_list_repos() -> dict[str, Any]:
    return scope_summary()


@app.put("/api/repos/scope")
def api_save_repo_scope(body: SaveRepoScopeRequest) -> dict[str, Any]:
    try:
        return write_scope(body.write_repo, body.read_repos)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/prompts")
def api_list_prompts() -> dict[str, Any]:
    return list_prompts_meta()


@app.get("/api/prompts/{agent_id}")
def api_get_prompt(agent_id: str, sector: str = "default") -> dict[str, Any]:
    try:
        return read_prompt(agent_id, sector)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/prompts/{agent_id}")
def api_save_prompt(agent_id: str, body: SavePromptRequest, sector: str = "default") -> dict[str, Any]:
    try:
        return write_prompt(agent_id, sector, body.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str) -> dict[str, Any]:
    try:
        run = load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    session_detail = None
    session_id = run.get("session_id")
    if session_id:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        session_path = SESSIONS_DIR / f"{safe}.json"
        if session_path.exists():
            data = _read_json(session_path)
            turns = _build_turns(data.get("messages") or [])
            session_detail = {
                **data,
                "turns": turns,
                "auto_issues": _auto_issues(turns),
            }
            _attach_qa_to_turns(turns, run.get("qa_report") if isinstance(run.get("qa_report"), dict) else None)

    fixes = enrich_fixes(
        run.get("fixes") if isinstance(run.get("fixes"), dict) else None,
        job_id=run.get("job_id"),
        qa_report=run.get("qa_report") if isinstance(run.get("qa_report"), dict) else None,
    )
    return {**run, "fixes": fixes, "session_detail": session_detail}


@app.get("/api/runs/{run_id}/improvements/export.json")
def export_improvements_json(run_id: str) -> Response:
    try:
        run = load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    fixes = enrich_fixes(
        run.get("fixes") if isinstance(run.get("fixes"), dict) else None,
        job_id=run.get("job_id"),
        qa_report=run.get("qa_report") if isinstance(run.get("qa_report"), dict) else None,
    )
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "product": "pivony-quality-loop-improvements",
        "run_id": run.get("run_id"),
        "created_at": run.get("created_at"),
        "session_id": run.get("session_id"),
        "job_id": run.get("job_id"),
        "sector": (run.get("session_detail") or {}).get("sector") if isinstance(run.get("session_detail"), dict) else None,
        "qa_report": run.get("qa_report"),
        "fixes": fixes,
        "summary": run.get("summary"),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = f"pivony-quality-loop-{run_id}-improvements.json"
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions")
def list_sessions() -> list[dict[str, Any]]:
    if not SESSIONS_DIR.exists():
        return []
    active_job = get_active_job()
    live_session_id = _best_live_session_id(active_job) if active_job else None
    rows: list[dict[str, Any]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append(
                _session_summary(
                    path,
                    active_job=active_job,
                    live_session_id=live_session_id,
                )
            )
        except (json.JSONDecodeError, ValueError, OSError):
            continue
    return rows


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    path = SESSIONS_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="session not found")
    data = _read_json(path)
    turns = _build_turns(data.get("messages") or [])
    linked_runs = [r for r in list_runs() if r.get("session_id") == session_id]
    linked_runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    latest_run = _latest_run_for_session(session_id)
    qa_report = latest_run.get("qa_report") if latest_run else None
    _attach_qa_to_turns(turns, qa_report if isinstance(qa_report, dict) else None)
    return {
        **data,
        "turns": turns,
        "turn_count": len(turns),
        "auto_issues": _auto_issues(turns),
        "linked_runs": linked_runs,
        "run_id": latest_run.get("run_id") if latest_run else None,
        "qa_report": qa_report,
        "modified_at": _file_mtime(path),
    }


def _load_session_detail(session_id: str) -> dict[str, Any]:
    return get_session(session_id)


@app.get("/api/runs/{run_id}/qa/export.json")
def export_run_qa_json(run_id: str) -> Response:
    try:
        run = load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    session_id = str(run.get("session_id") or "")
    meta = _qa_export_meta_from_run(run)
    payload = build_qa_export_json(session_id=session_id, meta=meta)
    filename = export_filename(session_id, "json", kind="qa", run_id=run_id)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/runs/{run_id}/qa/export.md")
def export_run_qa_markdown(run_id: str) -> Response:
    try:
        run = load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    session_id = str(run.get("session_id") or "")
    meta = _qa_export_meta_from_run(run)
    qa_payload = build_qa_export_json(session_id=session_id, meta=meta)
    lines = [
        "# Pivony Quality Loop — QA Report",
        f"Session: {session_id}",
        f"Run: {run_id}",
        f"Exported: {datetime.utcnow().strftime('%d %B %Y %H:%M')} UTC",
    ]
    qa = qa_payload.get("qa_report") or {}
    if qa.get("overall_verdict"):
        lines.append(f"Verdict: {qa['overall_verdict']}")
    if qa.get("priority_fix"):
        lines.append(f"Priority fix: {qa['priority_fix']}")
    if qa.get("scores"):
        lines.append("", "**Scores:**")
        for k, v in (qa.get("scores") or {}).items():
            lines.append(f"- {k}: {v}")
    if qa.get("issues"):
        lines.append("", "**Issues:**")
        for issue in qa["issues"]:
            sev = issue.get("severity")
            prefix = f"[{sev}] " if sev else ""
            lines.append(f"- {prefix}{issue.get('category', 'issue')}: {issue.get('description', '')}")
            if issue.get("fix_hint"):
                lines.append(f"  - Fix: {issue['fix_hint']}")
            if issue.get("evidence"):
                lines.append(f"  - Evidence: {issue['evidence']}")
    fixes = qa_payload.get("fixes") or {}
    applied = fixes.get("applied") or []
    skipped = fixes.get("skipped") or []
    if applied or skipped:
        lines.append("", "**Fixes:**")
        for fix in applied:
            lines.append(f"- [applied] {fix.get('file', 'N/A')}: {fix.get('issue', '')}")
        for fix in skipped:
            lines.append(f"- [skipped] {fix.get('file', 'N/A')}: {fix.get('issue', '')}")
    markdown = "\n".join(lines).strip() + "\n"
    filename = export_filename(session_id, "md", kind="qa", run_id=run_id)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.json")
def export_session_json(
    session_id: str,
    job_id: str | None = None,
    run_id: str | None = None,
    scope: Literal["conversation", "qa", "all"] = "conversation",
) -> Response:
    detail = _load_session_detail(session_id)
    extra: dict[str, Any] = {"job_id": job_id}
    if scope in ("qa", "all"):
        qa_meta = _qa_export_meta_from_session_detail(detail, run_id=run_id, job_id=job_id)
        extra.update(
            {
                "run_id": qa_meta.get("run_id"),
                "qa_report": qa_meta.get("qa_report"),
                "fixes": qa_meta.get("fixes"),
                "summary": qa_meta.get("summary"),
            }
        )
    payload, _ = export_payload_from_session_detail(detail, extra, scope=scope)
    kind = "qa" if scope == "qa" else "conversation" if scope == "conversation" else "all"
    filename = export_filename(
        session_id,
        "json",
        kind=kind,
        run_id=str(extra.get("run_id") or "") or None,
    )
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.md")
def export_session_markdown(
    session_id: str,
    job_id: str | None = None,
    run_id: str | None = None,
    scope: Literal["conversation", "qa", "all"] = "conversation",
) -> Response:
    detail = _load_session_detail(session_id)
    session_id_str = str(detail.get("session_id") or session_id)
    title = session_id_str[:18] + "…" if len(session_id_str) > 20 else session_id_str
    qa_meta = _qa_export_meta_from_session_detail(detail, run_id=run_id, job_id=job_id)
    meta = {
        "session_id": session_id_str,
        "sector": detail.get("sector"),
        "user_email": detail.get("user_email"),
        "user_id": detail.get("user_id"),
        "run_id": qa_meta.get("run_id"),
        "job_id": job_id,
        "turn_count": detail.get("turn_count"),
        "qa_report": qa_meta.get("qa_report") if scope != "conversation" else None,
        "fixes": qa_meta.get("fixes") if scope != "conversation" else None,
        "summary": qa_meta.get("summary") if scope != "conversation" else None,
    }
    if scope == "qa":
        qa_payload = build_qa_export_json(session_id=session_id_str, meta=meta)
        lines = [
            f"# Pivony Quality Loop — QA Report",
            f"Session: {session_id_str}",
            f"Exported: {datetime.utcnow().strftime('%d %B %Y %H:%M')} UTC",
        ]
        if meta.get("run_id"):
            lines.append(f"Run: {meta['run_id']}")
        qa = qa_payload.get("qa_report") or {}
        if qa.get("overall_verdict"):
            lines.append(f"Verdict: {qa['overall_verdict']}")
        if qa.get("priority_fix"):
            lines.append(f"Priority fix: {qa['priority_fix']}")
        if qa.get("scores"):
            lines.append("", "**Scores:**")
            for k, v in (qa.get("scores") or {}).items():
                lines.append(f"- {k}: {v}")
        if qa.get("issues"):
            lines.append("", "**Issues:**")
            for issue in qa["issues"]:
                sev = issue.get("severity")
                prefix = f"[{sev}] " if sev else ""
                lines.append(f"- {prefix}{issue.get('category', 'issue')}: {issue.get('description', '')}")
                if issue.get("fix_hint"):
                    lines.append(f"  - Fix: {issue['fix_hint']}")
        markdown = "\n".join(lines).strip() + "\n"
        filename = export_filename(
            session_id_str,
            "md",
            kind="qa",
            run_id=str(meta.get("run_id") or "") or None,
        )
    else:
        _, messages = export_payload_from_session_detail(detail, {"job_id": job_id}, scope="conversation")
        markdown = build_conversation_export_markdown(title=title, messages=messages, meta=meta)
        filename = export_filename(session_id_str, "md", kind="conversation")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/jobs/active/export.json")
def export_active_job_json() -> Response:
    job = get_active_job()
    if not job:
        raise HTTPException(status_code=404, detail="no active job")
    session_id = job.get("session_id")
    if not session_id:
        raise HTTPException(status_code=404, detail="active job has no session yet")
    return export_session_json(session_id, job_id=job.get("job_id"))


@app.get("/api/iterations")
def list_iterations() -> list[dict[str, Any]]:
    return _list_output_files("iteration_")


@app.get("/api/iterations/{name}")
def get_iteration(name: str) -> dict[str, Any]:
    path = OUTPUT_DIR / name
    if not path.exists() or not name.startswith("iteration_"):
        raise HTTPException(status_code=404, detail="iteration not found")
    data = _read_json(path)
    if data.get("run_id"):
        try:
            return {**load_run(str(data["run_id"])), "legacy_file": name}
        except FileNotFoundError:
            pass
    result_text = str(data.get("result") or "")
    return {
        **data,
        "result_text": result_text,
        "result_parsed": try_parse_json(result_text),
        "modified_at": _file_mtime(path),
    }


@app.get("/api/analyze")
def list_analyze() -> list[dict[str, Any]]:
    return _list_output_files("analyze_")


@app.get("/api/analyze/{name}")
def get_analyze(name: str) -> dict[str, Any]:
    path = OUTPUT_DIR / name
    if not path.exists() or not name.startswith("analyze_"):
        raise HTTPException(status_code=404, detail="analyze run not found")
    data = _read_json(path)
    if data.get("run_id"):
        try:
            return {**load_run(str(data["run_id"])), "legacy_file": name}
        except FileNotFoundError:
            pass
    result_text = str(data.get("result") or "")
    return {
        **data,
        "result_text": result_text,
        "result_parsed": try_parse_json(result_text),
        "modified_at": _file_mtime(path),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{view_name}")
def spa_shell(view_name: str) -> FileResponse:
    if view_name not in _SPA_VIEWS:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("QUALITY_LOOP_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("QUALITY_LOOP_UI_PORT", "8020"))
    uvicorn.run("quality_loop.ui.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
