"""Tests for deploy approval queue."""

import json

import pytest

from quality_loop import deploy_gate


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    queue = tmp_path / "deploy_queue.json"
    monkeypatch.setattr(deploy_gate, "QUEUE_PATH", queue)
    yield queue


def test_push_requires_approval_default_true(monkeypatch):
    monkeypatch.delenv("QUALITY_LOOP_REQUIRE_PUSH_APPROVAL", raising=False)
    assert deploy_gate.push_requires_approval() is True


def test_git_push_allowed_after_approval(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_ALLOW_GIT_PUSH", "true")
    monkeypatch.setenv("QUALITY_LOOP_REQUIRE_PUSH_APPROVAL", "true")
    deploy_gate.queue_push_approval(
        job_id="job_test",
        session_id="sess_x",
        fixes=[{"file": "a.py", "commit_hash": "deadbeef"}],
        commit_hashes=["deadbeef"],
    )
    assert deploy_gate.git_push_allowed(job_id="job_test") is False
    deploy_gate.approve_push("job_test", approved_by="tester")
    assert deploy_gate.git_push_allowed(job_id="job_test") is True


def test_approve_and_list_pending(isolated_queue):
    deploy_gate.queue_push_approval(
        job_id="job_a",
        session_id=None,
        fixes=[],
        commit_hashes=["111"],
    )
    pending = deploy_gate.list_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["job_id"] == "job_a"
    assert pending[0]["status"] == "pending"
    approved = deploy_gate.approve_push("job_a")
    assert approved["status"] == "approved"
    data = json.loads(isolated_queue.read_text(encoding="utf-8"))
    assert any(r.get("job_id") == "job_a" and r.get("status") == "approved" for r in data["pending"])
