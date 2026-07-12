"""Cursor SDK coding phase for the quality loop (hybrid Option A)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

from quality_loop.coding_git_finalize import capture_repo_states, finalize_cursor_fixes
from quality_loop.repo_scope import get_masterr_root, read_scope, repo_path
from quality_loop.run_store import try_parse_json

logger = logging.getLogger(__name__)


def coding_backend() -> str:
    return os.environ.get("QUALITY_LOOP_CODING_BACKEND", "cursor").strip().lower() or "cursor"


def cursor_runtime() -> str:
    return os.environ.get("QUALITY_LOOP_CURSOR_RUNTIME", "local").strip().lower() or "local"


def is_cursor_coding_enabled() -> bool:
    if coding_backend() != "cursor":
        return False
    if not os.environ.get("CURSOR_API_KEY", "").strip():
        return False
    try:
        import cursor_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def _coding_brief(sector: str | None) -> str:
    from quality_loop.prompt_config import read_prompt

    resolved = (sector or os.environ.get("QUALITY_LOOP_SECTOR") or "default").strip() or "default"
    return read_prompt("coding_agent", resolved)["content"]


def _scope_block() -> str:
    scope = read_scope()
    lines = [
        f"- write_repo: {scope.get('write_repo')}",
        f"- extra_write_repos: {', '.join(scope.get('extra_write_repos') or []) or '—'}",
        f"- read_repos: {', '.join(scope.get('read_repos') or []) or '—'}",
        f"- blocked: {', '.join(scope.get('blocked_write_repos') or [])}",
    ]
    masterr = get_masterr_root()
    lines.append(f"- masterr_root: {masterr}")
    for slug in [scope.get("write_repo"), *(scope.get("extra_write_repos") or [])]:
        if not slug:
            continue
        path = repo_path(slug)
        if path:
            lines.append(f"- {slug} path: {path}")
    return "\n".join(lines)


def build_cursor_coding_prompt(
    qa_report: dict[str, Any],
    *,
    session_id: str | None = None,
    sector: str | None = None,
) -> str:
    branch = os.environ.get("QUALITY_LOOP_GIT_BRANCH", "development").strip() or "development"
    qa_json = json.dumps(qa_report, ensure_ascii=False, indent=2)
    return (
        "You are the Pivony quality-loop Coding Agent.\n"
        "Fix QA issues in this monorepo with minimal, focused changes.\n\n"
        f"Session: {session_id or 'n/a'}\n"
        f"Git branch: ALWAYS work on `{branch}` only.\n\n"
        "## Repo scope\n"
        f"{_scope_block()}\n\n"
        "## Coding brief\n"
        f"{_coding_brief(sector)}\n\n"
        "## QA report (JSON)\n"
        f"{qa_json}\n\n"
        "## Instructions\n"
        "1. Start with critical/high severity issues.\n"
        "2. Read relevant files before editing; keep fixes minimal.\n"
        "3. Never write to pivony-api / pivony-api-dev.\n"
        "4. Do not manually escape Python source (no \\\" hacks in triple-quoted strings).\n"
        "5. Ensure every edited .py file passes Python syntax validation.\n"
        "6. Prefer editing files under the scoped write repos only.\n\n"
        "## Required final JSON (last message)\n"
        "Return a single JSON object:\n"
        "{\n"
        '  "fixes_applied": [{"repo":"...", "file":"...", "qa_issue_index":0, "issue_fixed":"...", "deploy_status":"file_written_and_valid"}],\n'
        '  "fixes_skipped": [{"repo":null, "file":"N/A", "qa_issue_index":1, "issue":"...", "reason":"..."}],\n'
        '  "next_test_scenarios": ["..."]\n'
        "}\n"
    )


def _model_selection():
    from cursor_sdk import ModelParameterValue, ModelSelection

    model_id = os.environ.get("QUALITY_LOOP_CURSOR_MODEL", "composer-2.5").strip() or "composer-2.5"
    fast = os.environ.get("QUALITY_LOOP_CURSOR_FAST", "true").strip().lower() in ("1", "true", "yes")
    params = []
    if fast:
        params.append(ModelParameterValue(id="fast", value="true"))
    return ModelSelection(id=model_id, params=params)


def _origin_https_url(repo_path: str | os.PathLike[str]) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    if not url:
        return None
    if url.startswith("git@"):
        host, path = url.split(":", 1)
        host = host.split("@", 1)[1]
        url = f"https://{host}/{path}"
    if url.endswith(".git"):
        url = url[:-4]
    return url


def _cloud_repositories():
    from cursor_sdk import CloudRepository

    from quality_loop.git_branch import git_target_branch

    branch = git_target_branch()
    repos = []
    scope = read_scope()
    seen: set[str] = set()
    for slug in [scope.get("write_repo"), *(scope.get("extra_write_repos") or [])]:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        path = repo_path(slug)
        if not path:
            continue
        url = _origin_https_url(path)
        if not url:
            logger.warning("skip cloud repo %s: no origin url", slug)
            continue
        repos.append(CloudRepository(url=url, starting_ref=branch))
    if not repos:
        raise RuntimeError("No cloud repositories resolved from repo scope")
    return repos


def _agent_options():
    from cursor_sdk import AgentOptions, CloudAgentOptions, LocalAgentOptions

    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY is required for cursor coding backend")

    model = _model_selection()
    runtime = cursor_runtime()
    if runtime == "cloud":
        return AgentOptions(
            api_key=api_key,
            model=model,
            cloud=CloudAgentOptions(repos=_cloud_repositories()),
        )
    masterr = get_masterr_root()
    return AgentOptions(
        api_key=api_key,
        model=model,
        local=LocalAgentOptions(cwd=str(masterr)),
    )


def _extract_assistant_text(run: Any) -> str:
    chunks: list[str] = []
    try:
        for turn in run.conversation():
            msg = getattr(turn, "message", None) or getattr(turn, "assistant_message", None)
            if msg is None:
                continue
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                chunks.append(content)
                continue
            if isinstance(content, list):
                for block in content:
                    text = getattr(block, "text", None)
                    if text:
                        chunks.append(str(text))
    except Exception as exc:
        logger.warning("conversation parse failed: %s", exc)
    return "\n".join(chunks).strip()


def _merge_fix_payload(cursor_json: dict[str, Any] | None, git_payload: dict[str, Any]) -> dict[str, Any]:
    if not cursor_json:
        return git_payload
    merged = dict(git_payload)
    for key in ("fixes_applied", "fixes_skipped", "next_test_scenarios"):
        cursor_val = cursor_json.get(key)
        git_val = git_payload.get(key)
        if cursor_val and not git_val:
            merged[key] = cursor_val
    merged["cursor_summary"] = cursor_json
    return merged


def run_cursor_coding(
    qa_report: dict[str, Any],
    *,
    session_id: str | None = None,
    sector: str | None = None,
    job_id: str = "",
) -> dict[str, Any]:
    """Execute Cursor Composer coding phase; return phase dict for run_store."""
    from cursor_sdk import Agent, CursorAgentError

    prompt = build_cursor_coding_prompt(qa_report, session_id=session_id, sector=sector)
    before_states = capture_repo_states()
    log_lines = [
        f"Cursor coding backend ({cursor_runtime()}, model={os.environ.get('QUALITY_LOOP_CURSOR_MODEL', 'composer-2.5')})"
    ]
    transcript = ""

    try:
        with Agent.create(_agent_options()) as agent:
            run = agent.send(prompt)
            result = run.wait()
            transcript = _extract_assistant_text(run)
            if not transcript and result is not None:
                transcript = str(getattr(result, "result", "") or "")
            status = getattr(result, "status", None) or getattr(run, "status", None)
            if status == "error":
                raise RuntimeError(f"Cursor run failed (status=error): {transcript[:500]}")
    except CursorAgentError as exc:
        payload = {
            "fixes_applied": [],
            "fixes_skipped": [
                {
                    "file": "N/A",
                    "repo": None,
                    "issue": "cursor startup",
                    "reason": str(exc),
                }
            ],
            "next_test_scenarios": [],
            "coding_backend": "cursor",
        }
        return {
            "phase": "coding",
            "agent": "Cursor Composer",
            "task_description": "Cursor SDK coding phase (hybrid)",
            "raw_output": transcript or str(exc),
            "parsed_output": payload,
        }
    except Exception as exc:
        payload = {
            "fixes_applied": [],
            "fixes_skipped": [
                {
                    "file": "N/A",
                    "repo": None,
                    "issue": "cursor coding",
                    "reason": str(exc),
                }
            ],
            "next_test_scenarios": [],
            "coding_backend": "cursor",
        }
        return {
            "phase": "coding",
            "agent": "Cursor Composer",
            "task_description": "Cursor SDK coding phase (hybrid)",
            "raw_output": transcript or str(exc),
            "parsed_output": payload,
        }

    cursor_json = try_parse_json(transcript)
    if cursor_json is None:
        match = re.search(r"(\{[\s\S]*\"fixes_applied\"[\s\S]*\})", transcript)
        if match:
            cursor_json = try_parse_json(match.group(1))

    git_payload, git_logs = finalize_cursor_fixes(
        before_states,
        job_id=job_id or os.environ.get("QUALITY_LOOP_JOB_ID", ""),
        qa_report=qa_report,
        runtime=cursor_runtime(),
    )
    log_lines.extend(git_logs)
    payload = _merge_fix_payload(cursor_json if isinstance(cursor_json, dict) else None, git_payload)
    payload["coding_backend"] = "cursor"
    payload["cursor_runtime"] = cursor_runtime()

    raw_output = transcript
    if log_lines:
        raw_output = f"{transcript}\n\n--- git finalize ---\n" + "\n".join(log_lines)

    return {
        "phase": "coding",
        "agent": "Cursor Composer",
        "task_description": "Cursor SDK coding phase (hybrid)",
        "raw_output": raw_output,
        "parsed_output": payload,
    }
