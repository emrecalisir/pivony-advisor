"""Tests for deploy approval queue."""

import json
import subprocess

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


def test_commits_ahead_of_origin_detects_local_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "development"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "second"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-f", "origin/dev-anchor", "HEAD~1"], cwd=repo, check=True, capture_output=True)
    origin = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "origin/dev-anchor"], text=True
    ).strip()
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    ahead = deploy_gate.commits_ahead_of_origin(repo, head=head, origin=origin)
    assert len(ahead) == 1


def test_dev_auto_approve_enabled_only_on_dev_target(monkeypatch):
    monkeypatch.setenv("QUALITY_LOOP_DEV_AUTO_APPROVE", "true")
    monkeypatch.setenv("QUALITY_LOOP_DEPLOY_TARGET", "prod")
    assert deploy_gate.dev_auto_approve_enabled() is False
    monkeypatch.setenv("QUALITY_LOOP_DEPLOY_TARGET", "dev")
    assert deploy_gate.dev_auto_approve_enabled() is True


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
