"""Per-repo git write lock during coding finalize (development branch)."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from typing import IO

_PACKAGE_ROOT = Path(__file__).resolve().parent
LOCK_DIR = _PACKAGE_ROOT / "outputs" / "jobs" / "git_locks"


class GitWriteLockBusy(RuntimeError):
    pass


def _lock_path(repo_slug: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_slug)
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_DIR / f"{safe}.lock"


def acquire_git_write_lock(
    repo_slug: str,
    *,
    block: bool = True,
    timeout_sec: float = 600.0,
) -> IO[str]:
    path = _lock_path(repo_slug)
    fh = open(path, "a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while True:
        try:
            flags = fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), flags)
            fh.seek(0)
            fh.truncate()
            fh.write(f"pid={os.getpid()}\n")
            fh.flush()
            return fh
        except BlockingIOError:
            if not block or time.monotonic() >= deadline:
                fh.close()
                raise GitWriteLockBusy(f"git write lock busy for {repo_slug}")
            time.sleep(1.0)


def release_git_write_lock(fh: IO[str] | None) -> None:
    if fh is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()
