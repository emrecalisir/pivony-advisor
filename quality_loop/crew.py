"""Pivony Advisor Quality Loop — CrewAI crew runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# CrewAI supports Python >=3.10 and <3.14 only.
if sys.version_info >= (3, 14):
    raise SystemExit(
        "CrewAI requires Python >=3.10 and <3.14. "
        "Use: bash scripts/bootstrap-quality-loop-venv.sh && bash scripts/run_quality_loop.sh"
    )

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=False)

from quality_loop.repo_scope import apply_scope_to_env

for _key, _val in apply_scope_to_env().items():
    if _key in ("PIVONY_REPO_ROOT", "QUALITY_LOOP_REPO_SCOPE", "QUALITY_LOOP_API_REPO"):
        os.environ[_key] = _val

from quality_loop.langsmith_tracing import configure_langsmith_tracing
from quality_loop.vertex_resilience import (
    configure_vertex_resilience,
    is_rate_limit_error,
    set_status_callback,
    user_message_for_rate_limit_exhausted,
)

configure_langsmith_tracing()
configure_vertex_resilience()

from crewai import Crew, Process

from quality_loop.agents import _resolve_sector, create_agents
from quality_loop.run_store import save_run
from quality_loop.tasks import create_analyze_tasks, create_tasks

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
_JOB_ID: str | None = None


def _advisor_url() -> str:
    return os.environ.get("PIVONY_ADVISOR_URL", "http://127.0.0.1:8011")


def _write_legacy_file(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _update_job(**patch) -> None:
    if not _JOB_ID:
        return
    from quality_loop.run_manager import write_job

    clean = {k: v for k, v in patch.items() if v is not None}
    write_job(_JOB_ID, clean)


def _vertex_status_callback(patch: dict) -> None:
    _update_job(**patch)


def _latest_session_id() -> str | None:
    """Session created for the current job only (never reuse a pre-job session)."""
    sessions_dir = OUTPUT_DIR / "sessions"
    if not sessions_dir.exists():
        return None

    job_started: str | None = None
    pinned_sid: str | None = None
    if _JOB_ID:
        try:
            from quality_loop.run_manager import load_job

            job = load_job(_JOB_ID)
            job_started = job.get("started_at")
            pinned_sid = job.get("session_id")
        except FileNotFoundError:
            pass

    if pinned_sid:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pinned_sid)
        path = sessions_dir / f"{safe}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                created = data.get("created_at") or ""
                if not job_started or not created or created >= job_started:
                    return data.get("session_id") or pinned_sid
            except (json.JSONDecodeError, OSError):
                return pinned_sid

    best_id: str | None = None
    best_created = ""
    for path in sessions_dir.glob("sess_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        created = data.get("created_at") or ""
        if job_started and created and created < job_started:
            continue
        sid = data.get("session_id") or path.stem
        if created >= best_created:
            best_created = created
            best_id = sid
    return best_id


def _qa_report_from_task(qa_task: Any) -> dict[str, Any] | None:
    output = getattr(qa_task, "output", None)
    if output is None:
        return None
    parsed = getattr(output, "json_dict", None)
    if isinstance(parsed, dict):
        return parsed
    from quality_loop.run_store import try_parse_json

    return try_parse_json(str(getattr(output, "raw", None) or output))


def _run_cursor_coding_if_enabled(
    qa_task: Any,
    *,
    session_id: str | None,
    sector: str | None,
) -> dict[str, Any] | None:
    from quality_loop.coding_cursor import is_cursor_coding_enabled, run_cursor_coding

    if not is_cursor_coding_enabled():
        return None
    qa_report = _qa_report_from_task(qa_task)
    if not isinstance(qa_report, dict):
        qa_report = {"issues": [], "overall_verdict": "unknown"}
    return run_cursor_coding(
        qa_report,
        session_id=session_id,
        sector=sector,
        job_id=os.environ.get("QUALITY_LOOP_JOB_ID", ""),
    )


def _run_verification_if_enabled(
    *,
    session_id: str | None,
    cursor_phase: dict[str, Any] | None,
    qa_task: Any,
) -> dict[str, Any] | None:
    from quality_loop.loop_insights import auto_verify_enabled
    from quality_loop.regression import run_regression_verification

    if not auto_verify_enabled() or not session_id:
        return None
    scenarios: list[str] = []
    if isinstance(cursor_phase, dict):
        fixes = cursor_phase.get("fixes") or cursor_phase
        if isinstance(fixes, dict):
            scenarios = list(fixes.get("next_test_scenarios") or [])
    if not scenarios:
        qa_report = _qa_report_from_task(qa_task)
        if isinstance(qa_report, dict):
            for issue in qa_report.get("issues") or []:
                if isinstance(issue, dict) and issue.get("issue_class") in ("code", None):
                    desc = (issue.get("description") or "")[:120]
                    if desc:
                        scenarios.append(f"Doğrula: {desc}")
    _update_job(phase="verify", message="Regression senaryoları doğrulanıyor")
    result = run_regression_verification(session_id, scenarios)
    return {
        "phase": "verification",
        "agent": "Regression Gate",
        "parsed_output": result,
        "status": result.get("status"),
    }


def _phase_rows(
    conversation_task: Any | None,
    qa_task: Any,
    coding_task: Any | None,
    *,
    cursor_phase: dict[str, Any] | None = None,
) -> list[tuple]:
    rows: list[tuple] = []
    if conversation_task is not None:
        rows.append((conversation_task, "conversation", "CX Director"))
    rows.append((qa_task, "qa", "QA Agent"))
    if coding_task is not None:
        rows.append((coding_task, "coding", "Coding Agent"))
    return rows


def _additional_phases(cursor_phase: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if cursor_phase is None:
        return None
    return [cursor_phase]


def _session_turn_count(session_id: str | None) -> int:
    if not session_id:
        return 0
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    path = OUTPUT_DIR / "sessions" / f"{safe}.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return sum(1 for m in data.get("messages") or [] if m.get("role") == "user")
    except (json.JSONDecodeError, OSError):
        return 0


def _kickoff_crew(crew: Crew, *, phase: str, message: str, mode: str = "full") -> object:
    import threading
    import time

    from quality_loop.langsmith_tracing import run_trace_context

    stop = threading.Event()

    def _poll_session() -> None:
        while not stop.wait(5):
            sid = _latest_session_id()
            if sid:
                _update_job(
                    session_id=sid,
                    turn_count=_session_turn_count(sid),
                )

    _update_job(phase=phase, message=message, session_id=_latest_session_id())
    poller = threading.Thread(target=_poll_session, daemon=True)
    poller.start()
    try:
        with run_trace_context(job_id=_JOB_ID, mode=mode, session_id=_latest_session_id()):
            result = crew.kickoff()
    finally:
        stop.set()
        poller.join(timeout=1)
    _update_job(
        phase=phase,
        message=f"{message} — tamamlandı",
        session_id=_latest_session_id(),
        turn_count=_session_turn_count(_latest_session_id()),
    )
    return result


def run_loop(iterations: int = 1) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(1, iterations + 1):
        print(f"\n{'=' * 60}")
        print(f"  QUALITY LOOP — İTERASYON {i}/{iterations}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}\n")

        _update_job(
            iteration=i,
            phase="conversation",
            message=f"İterasyon {i}: CX Director Advisor ile konuşuyor (6-10 tur)",
        )

        sector = _resolve_sector()
        from quality_loop.loop_insights import collect_regression_scenarios

        regression = collect_regression_scenarios(exclude_session_id=_latest_session_id())
        cx_director, qa_agent, coding_agent = create_agents(sector)
        conversation_task, qa_task, coding_task = create_tasks(
            cx_director, qa_agent, coding_agent, sector=sector, regression_scenarios=regression
        )

        tasks = [t for t in (conversation_task, qa_task, coding_task) if t is not None]
        agents = [a for a in (cx_director, qa_agent, coding_agent) if a is not None]

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )

        # CrewAI runs tasks sequentially; session file grows during conversation task.
        result = _kickoff_crew(
            crew,
            phase="conversation",
            message=f"İterasyon {i}: loop çalışıyor (konuşma → QA → coding)",
            mode="full",
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        from quality_loop.coding_cursor import is_cursor_coding_enabled

        if is_cursor_coding_enabled():
            _update_job(phase="coding", message="Cursor Composer fix'leri uyguluyor")
        else:
            _update_job(phase="coding", message="Coding Agent iyileştirme önerilerini uyguluyor")

        cursor_phase = _run_cursor_coding_if_enabled(
            qa_task,
            session_id=_latest_session_id(),
            sector=sector,
        )
        phase_rows = _phase_rows(conversation_task, qa_task, coding_task)

        verification_phase = _run_verification_if_enabled(
            session_id=_latest_session_id(),
            cursor_phase=cursor_phase,
            qa_task=qa_task,
        )
        extra_phases = _additional_phases(cursor_phase)
        if verification_phase:
            extra_phases = (extra_phases or []) + [verification_phase]

        run_path = save_run(
            mode="full",
            tasks=phase_rows,
            final_result=result,
            iteration=i,
            advisor_url=_advisor_url(),
            job_id=_JOB_ID,
            additional_phases=extra_phases,
            verification=verification_phase,
        )

        run_data = json.loads(run_path.read_text(encoding="utf-8"))
        legacy = OUTPUT_DIR / f"iteration_{i}_{timestamp}.json"
        _write_legacy_file(
            legacy,
            {
                "iteration": i,
                "timestamp": timestamp,
                "run_id": run_data.get("run_id"),
                "session_id": run_data.get("session_id"),
                "result": str(result),
                "qa_report": run_data.get("qa_report"),
                "fixes": run_data.get("fixes"),
                "phases": run_data.get("phases"),
                "summary": run_data.get("summary"),
                "pivony_advisor_url": _advisor_url(),
            },
        )

        _update_job(
            phase="done",
            message="Run tamamlandı",
            run_id=run_data.get("session_id") or run_data.get("run_id"),
            cycle_id=run_data.get("session_id") or run_data.get("run_id"),
            session_id=run_data.get("session_id"),
            qa_verdict=(run_data.get("qa_report") or {}).get("overall_verdict"),
            issue_count=(run_data.get("summary") or {}).get("issue_count"),
        )
        print(f"\n[Loop] İterasyon {i} tamamlandı → {run_path}")
        print(f"[Loop] Legacy snapshot → {legacy}")

    print(f"\n[Loop] {iterations} iterasyon tamamlandı.")


def run_analyze(session_id: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _update_job(phase="qa", message="QA Agent mevcut session'ı değerlendiriyor", session_id=session_id)

    sector = _resolve_sector()
    _, qa_agent, coding_agent = create_agents(sector)
    qa_task, coding_task = create_analyze_tasks(
        session_id, qa_agent, coding_agent, sector=sector
    )

    agents = [a for a in (qa_agent, coding_agent) if a is not None]
    tasks = [t for t in (qa_task, coding_task) if t is not None]

    crew = Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )
    result = _kickoff_crew(crew, phase="qa", message="Analyze: QA + coding", mode="analyze")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    from quality_loop.coding_cursor import is_cursor_coding_enabled

    if is_cursor_coding_enabled():
        _update_job(phase="coding", message="Cursor Composer fix'leri uyguluyor", session_id=session_id)

    cursor_phase = _run_cursor_coding_if_enabled(
        qa_task,
        session_id=session_id,
        sector=sector,
    )
    phase_rows = _phase_rows(None, qa_task, coding_task)

    verification_phase = _run_verification_if_enabled(
        session_id=session_id,
        cursor_phase=cursor_phase,
        qa_task=qa_task,
    )
    extra_phases = _additional_phases(cursor_phase)
    if verification_phase:
        extra_phases = (extra_phases or []) + [verification_phase]

    run_path = save_run(
        mode="analyze",
        tasks=phase_rows,
        final_result=result,
        session_id=session_id,
        advisor_url=_advisor_url(),
        job_id=_JOB_ID,
        additional_phases=extra_phases,
        verification=verification_phase,
    )

    run_data = json.loads(run_path.read_text(encoding="utf-8"))
    legacy = OUTPUT_DIR / f"analyze_{session_id}_{timestamp}.json"
    _write_legacy_file(
        legacy,
        {
            "session_id": session_id,
            "timestamp": timestamp,
            "run_id": run_data.get("run_id"),
            "result": str(result),
            "qa_report": run_data.get("qa_report"),
            "fixes": run_data.get("fixes"),
            "phases": run_data.get("phases"),
            "summary": run_data.get("summary"),
        },
    )
    _update_job(
        phase="done",
        run_id=session_id,
        cycle_id=session_id,
        session_id=session_id,
        qa_verdict=(run_data.get("qa_report") or {}).get("overall_verdict"),
    )
    print(f"\n[Analyze] Tamamlandı → {run_path}")


def main() -> None:
    global _JOB_ID
    parser = argparse.ArgumentParser(description="Pivony Advisor Quality Loop")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--mode", choices=["full", "analyze"], default="full")
    parser.add_argument("--session", type=str, default=None)
    parser.add_argument("--job-id", type=str, default=None)
    args = parser.parse_args()
    _JOB_ID = args.job_id

    cli_lock_fh = None
    if not _JOB_ID:
        from quality_loop.job_lock import JobLockBusy, acquire_job_lock, release_job_lock

        _JOB_ID = f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.environ["QUALITY_LOOP_JOB_ID"] = _JOB_ID
        try:
            cli_lock_fh = acquire_job_lock(_JOB_ID, block=False)
        except JobLockBusy as exc:
            raise SystemExit(str(exc)) from exc

    if _JOB_ID:
        set_status_callback(_vertex_status_callback)
        _update_job(status="running", message="Başlatılıyor")

    try:
        if args.mode == "analyze":
            if not args.session:
                parser.error("--mode analyze requires --session <session_id>")
            run_analyze(args.session)
        else:
            run_loop(iterations=args.iterations)
    except Exception as exc:
        if is_rate_limit_error(exc):
            msg = user_message_for_rate_limit_exhausted()
        else:
            msg = str(exc)
        _update_job(status="failed", phase="error", message=msg)
        raise
    else:
        if _JOB_ID:
            _update_job(
                status="completed",
                phase="done",
                message="Tamamlandı",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
    finally:
        set_status_callback(None)
        if cli_lock_fh is not None:
            from quality_loop.job_lock import release_job_lock

            release_job_lock(cli_lock_fh)


if __name__ == "__main__":
    main()
