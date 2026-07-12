"""Tests for quality-loop job lock."""

from __future__ import annotations

import os
from unittest.mock import patch

from quality_loop.job_lock import (
    JobLockBusy,
    acquire_job_lock,
    job_queue_mode,
    release_job_lock,
)


def test_job_queue_mode_default_reject(monkeypatch):
    monkeypatch.delenv("QUALITY_LOOP_JOB_QUEUE_MODE", raising=False)
    assert job_queue_mode() == "reject"


def test_acquire_and_release_job_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("quality_loop.job_lock.JOBS_DIR", tmp_path)
    monkeypatch.setattr("quality_loop.job_lock.JOB_LOCK_PATH", tmp_path / ".quality_loop_job.lock")
    fh1 = acquire_job_lock("job_a", block=False)
    try:
        try:
            acquire_job_lock("job_b", block=False)
            raised = False
        except JobLockBusy:
            raised = True
        assert raised
    finally:
        release_job_lock(fh1)
    fh2 = acquire_job_lock("job_c", block=False)
    release_job_lock(fh2)
