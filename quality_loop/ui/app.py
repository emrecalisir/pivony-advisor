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
from quality_loop.ui.export_builder import (
    build_conversation_export_markdown,
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
    """Allow SPA shell + static assets without token (API routes stay protected)."""
    rel = _app_relative_path(path)
    if rel in ("/", ""):
        return True
    if rel.startswith("/static") or "/static/" in path:
        return True
    view = rel.strip("/").split("/")[0] if rel.strip("/") else ""
    if view in _SPA_VIEWS:
        return True
    return rel.endswith((".css", ".js", ".ico", ".png", ".svg", ".woff2"))


@app.middleware("http")
async def optional_token_guard(request: Request, call_next):
    if not _UI_TOKEN:
        return await call_next(request)
    path = request.url.path
    if _is_public_asset(path):
        return await call_next(request)
    token = request.headers.get("x-quality-loop-token") or request.query_params.get("token")
    if token != _UI_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "invalid or missing token"})
    return await call_next(request)


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


def _session_summary(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    messages = data.get("messages") or []
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    tool_count = sum(len(m.get("toolActions") or []) for m in messages if m.get("role") == "assistant")
    preview = ""
    for msg in messages:
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            preview = str(msg["content"]).strip().replace("\n", " ")[:120]
            break
    return {
        "session_id": data.get("session_id") or path.stem,
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "user_id": data.get("user_id"),
        "user_email": data.get("user_email"),
        "turn_count": user_turns,
        "message_count": len(messages),
        "tool_action_count": tool_count,
        "sector": data.get("sector"),
        "advisor_mode": data.get("advisor_mode"),
        "preview": preview,
        "file": path.name,
        "modified_at": _file_mtime(path),
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
        for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                sessions.append(_session_summary(path))
            except (json.JSONDecodeError, ValueError, OSError):
                continue

    total_issues = sum((r.get("summary") or {}).get("issue_count", 0) for r in runs)
    total_fixes = sum((r.get("summary") or {}).get("fixes_applied", 0) for r in runs)

    return {
        "output_dir": str(OUTPUT_DIR),
        "counts": {
            "runs": len(runs),
            "sessions": len(sessions),
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
    rows: list[dict[str, Any]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append(_session_summary(path))
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


@app.get("/api/sessions/{session_id}/export.json")
def export_session_json(session_id: str, job_id: str | None = None) -> Response:
    detail = _load_session_detail(session_id)
    payload, _ = export_payload_from_session_detail(detail, {"job_id": job_id})
    filename = export_filename(session_id, "json")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.md")
def export_session_markdown(session_id: str, job_id: str | None = None) -> Response:
    detail = _load_session_detail(session_id)
    _, messages = export_payload_from_session_detail(detail, {"job_id": job_id})
    session_id_str = str(detail.get("session_id") or session_id)
    title = session_id_str[:18] + "…" if len(session_id_str) > 20 else session_id_str
    markdown = build_conversation_export_markdown(
        title=title,
        messages=messages,
        meta={
            "session_id": session_id_str,
            "sector": detail.get("sector"),
            "user_email": detail.get("user_email"),
            "user_id": detail.get("user_id"),
            "run_id": detail.get("run_id"),
            "job_id": job_id,
            "turn_count": detail.get("turn_count"),
            "qa_report": detail.get("qa_report"),
        },
    )
    filename = export_filename(session_id_str, "md")
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
