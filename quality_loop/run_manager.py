"""Background job orchestration for UI-triggered quality loop runs."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = _PACKAGE_ROOT / "outputs"
JOBS_DIR = OUTPUT_DIR / "jobs"
_REPO_ROOT = _PACKAGE_ROOT.parent

_lock = threading.Lock()
_active_job_id: str | None = None
_processes: dict[str, subprocess.Popen] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
    return JOBS_DIR / f"{safe}.json"


def write_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    path = _job_path(job_id)
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.update(patch)
    data["job_id"] = job_id
    data["updated_at"] = _utcnow_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    return True


def reconcile_stale_jobs() -> None:
    """Mark running jobs as failed when their process no longer exists."""
    if not JOBS_DIR.exists():
        return
    for path in JOBS_DIR.glob("job_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") not in ("queued", "running"):
            continue
        job_id = data.get("job_id") or path.stem
        proc = _processes.get(job_id)
        if proc is not None and proc.poll() is None:
            continue
        if _pid_alive(data.get("pid")):
            continue
        write_job(
            job_id,
            {
                "status": "failed",
                "phase": "error",
                "message": "Process sonlandı (zombie job temizlendi)",
                "finished_at": _utcnow_iso(),
            },
        )


def get_active_job() -> dict[str, Any] | None:
    reconcile_stale_jobs()
    if not JOBS_DIR.exists():
        return None
    jobs: list[dict[str, Any]] = []
    for path in JOBS_DIR.glob("job_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") in ("queued", "running"):
                jobs.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    if not jobs:
        return None
    jobs.sort(key=lambda j: j.get("started_at") or "", reverse=True)
    return jobs[0]


def _python_executable() -> str:
    venv_py = _REPO_ROOT / ".venv-quality-loop" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _spawn_job(*, mode: str, iterations: int = 1, session_id: str | None = None) -> dict[str, Any]:
    global _active_job_id
    with _lock:
        reconcile_stale_jobs()
        active = get_active_job()
        if active:
            raise RuntimeError(f"Job already running: {active['job_id']}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_id = f"job_{stamp}"
        _active_job_id = job_id

        cmd = [
            _python_executable(),
            "-m",
            "quality_loop.crew",
            "--job-id",
            job_id,
            "--mode",
            mode,
        ]
        if mode == "full":
            cmd.extend(["--iterations", str(iterations)])
        elif session_id:
            cmd.extend(["--session", session_id])

        log_path = OUTPUT_DIR / "jobs" / f"{job_id}.log"
        JOBS_DIR.mkdir(parents=True, exist_ok=True)

        write_job(
            job_id,
            {
                "status": "queued",
                "phase": "queued",
                "mode": mode,
                "iterations": iterations,
                "session_id": session_id,
                "started_at": _utcnow_iso(),
                "message": "Kuyruğa alındı",
                "log_file": str(log_path),
            },
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

        log_fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(_REPO_ROOT),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _processes[job_id] = proc
        write_job(job_id, {"pid": proc.pid, "status": "running", "message": "Çalışıyor"})

        def _wait() -> None:
            global _active_job_id
            code = proc.wait()
            log_fh.close()
            _processes.pop(job_id, None)
            try:
                current = load_job(job_id)
            except FileNotFoundError:
                current = {}
            if current.get("status") == "cancelled":
                pass
            elif code == 0:
                write_job(
                    job_id,
                    {
                        "status": "completed",
                        "phase": "done",
                        "message": "Tamamlandı",
                        "exit_code": code,
                        "finished_at": _utcnow_iso(),
                    },
                )
            else:
                patch: dict[str, Any] = {
                    "status": "failed",
                    "phase": "error",
                    "exit_code": code,
                    "finished_at": _utcnow_iso(),
                }
                if not current.get("message") or current.get("message") == "Çalışıyor":
                    patch["message"] = f"Hata (exit {code})"
                write_job(job_id, patch)
            with _lock:
                if _active_job_id == job_id:
                    _active_job_id = None

        threading.Thread(target=_wait, daemon=True).start()
        return load_job(job_id)


def start_full_loop(iterations: int = 1) -> dict[str, Any]:
    return _spawn_job(mode="full", iterations=iterations)


def start_analyze(session_id: str) -> dict[str, Any]:
    return _spawn_job(mode="analyze", session_id=session_id)


def stop_job(job_id: str | None = None) -> dict[str, Any]:
    global _active_job_id
    with _lock:
        if job_id is None:
            active = get_active_job()
            if not active:
                raise RuntimeError("No active job to stop")
            job_id = active["job_id"]

        try:
            job = load_job(job_id)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Job not found: {job_id}") from exc

        if job.get("status") not in ("queued", "running"):
            raise RuntimeError(f"Job not running: {job.get('status')}")

        pid = job.get("pid")
        proc = _processes.get(job_id)

        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(10):
                if proc.poll() is not None:
                    break
                time.sleep(0.3)
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        elif pid:
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass

        write_job(
            job_id,
            {
                "status": "cancelled",
                "phase": "cancelled",
                "message": "Kullanıcı tarafından durduruldu",
                "finished_at": _utcnow_iso(),
            },
        )
        _processes.pop(job_id, None)
        if _active_job_id == job_id:
            _active_job_id = None
        return load_job(job_id)
