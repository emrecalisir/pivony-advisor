"""Cross-process job lock — tek aktif quality-loop job (Prensip 4)."""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

_PACKAGE_ROOT = Path(__file__).resolve().parent
JOBS_DIR = _PACKAGE_ROOT / "outputs" / "jobs"
JOB_LOCK_PATH = JOBS_DIR / ".quality_loop_job.lock"


class JobLockBusy(RuntimeError):
    """Another quality-loop job holds the global lock."""


@dataclass
class JobLockInfo:
    job_id: str
    pid: int
    started_at: str
    host: str = ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, TypeError, PermissionError):
        return False
    return True


def read_job_lock() -> JobLockInfo | None:
    if not JOB_LOCK_PATH.exists():
        return None
    try:
        data = json.loads(JOB_LOCK_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("job_id"):
            return None
        return JobLockInfo(
            job_id=str(data["job_id"]),
            pid=int(data.get("pid") or 0),
            started_at=str(data.get("started_at") or ""),
            host=str(data.get("host") or ""),
        )
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return None


def _write_lock_metadata(fh: IO[str], job_id: str) -> None:
    payload = {
        "job_id": job_id,
        "pid": os.getpid(),
        "started_at": _utcnow_iso(),
        "host": os.uname().nodename if hasattr(os, "uname") else "",
    }
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps(payload, ensure_ascii=False))
    fh.flush()


def _try_acquire(fh: IO[str], job_id: str) -> bool:
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    _write_lock_metadata(fh, job_id)
    return True


def acquire_job_lock(
    job_id: str,
    *,
    block: bool = False,
    timeout_sec: float = 3600.0,
) -> IO[str]:
    """Acquire global job lock; returns open file handle (must be closed to release)."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(JOB_LOCK_PATH, "a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while True:
        if _try_acquire(fh, job_id):
            return fh
        if not block:
            fh.close()
            info = read_job_lock()
            holder = info.job_id if info else "unknown"
            raise JobLockBusy(f"Job already running: {holder}")
        if time.monotonic() >= deadline:
            fh.close()
            raise JobLockBusy(f"Timed out waiting for job lock ({timeout_sec}s)")
        time.sleep(2.0)


def release_job_lock(fh: IO[str] | None) -> None:
    if fh is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def reconcile_stale_job_lock() -> JobLockInfo | None:
    """Clear lock metadata when holder PID is dead (crash/kill)."""
    info = read_job_lock()
    if not info or not info.pid:
        return info
    if _pid_alive(info.pid):
        return info
    try:
        JOB_LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def job_queue_mode() -> str:
    return os.environ.get("QUALITY_LOOP_JOB_QUEUE_MODE", "reject").strip().lower() or "reject"


def job_queue_timeout_sec() -> float:
    raw = os.environ.get("QUALITY_LOOP_JOB_QUEUE_TIMEOUT_SEC", "3600").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 3600.0
