"""Smoke test for Cursor cloud coding backend connectivity."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=False)


def _check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def run_checks(*, live: bool = False) -> int:
    from quality_loop.coding_cursor import (
        _agent_options,
        _cloud_repositories,
        cursor_runtime,
        is_cursor_coding_enabled,
    )
    from quality_loop.cursor_context import build_previous_fixes_summary
    from quality_loop.job_lock import read_job_lock, reconcile_stale_job_lock
    from quality_loop.repo_scope import get_masterr_root, scope_summary

    ok = True
    ok &= _check("masterr_root", get_masterr_root().exists(), str(get_masterr_root()))
    scope = scope_summary()
    ok &= _check("write_repo", bool(scope.get("write_path")), str(scope.get("write_path")))
    ok &= _check(
        "CURSOR_API_KEY",
        bool(os.environ.get("CURSOR_API_KEY", "").strip()),
        "set" if os.environ.get("CURSOR_API_KEY") else "missing",
    )
    ok &= _check("cursor_sdk import", _import_cursor_sdk(), "")
    ok &= _check("cursor backend enabled", is_cursor_coding_enabled(), cursor_runtime())
    reconcile_stale_job_lock()
    lock = read_job_lock()
    ok &= _check("job lock free", lock is None, lock.job_id if lock else "no active lock")

    if cursor_runtime() == "cloud":
        try:
            repos = _cloud_repositories()
            ok &= _check("cloud repos", len(repos) > 0, f"{len(repos)} repo(s)")
            for repo in repos:
                url = getattr(repo, "url", None) or str(repo)
                print(f"       - {url}")
        except Exception as exc:
            ok &= _check("cloud repos", False, str(exc))
    else:
        ok &= _check("local cwd", True, str(get_masterr_root()))

    summary = build_previous_fixes_summary(limit=3)
    ok &= _check("context injection", len(summary) > 0, f"{len(summary)} chars")

    if not live:
        print("\nDry-run complete. Use --live for a minimal Cursor API ping.")
        return 0 if ok else 1

    if not is_cursor_coding_enabled():
        print("Cannot run --live: cursor backend not enabled")
        return 1

    print("\nLive ping: Cursor agent (read-only, no file edits)...")
    try:
        from cursor_sdk import Agent, CursorAgentError

        opts = _agent_options()
        prompt = (
            "Smoke test only. Do NOT modify any files. "
            'Reply with JSON: {"smoke":"ok","runtime":"'
            + cursor_runtime()
            + '"}'
        )
        with Agent.create(opts) as agent:
            run = agent.send(prompt)
            result = run.wait()
        status = getattr(result, "status", None) or getattr(run, "status", None)
        text = str(getattr(result, "result", "") or "")[:400]
        ok &= _check("cursor live run", status in (None, "finished", "completed"), f"status={status}")
        print(f"       response snippet: {text[:200]}")
        parsed = None
        try:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except (json.JSONDecodeError, ValueError):
            pass
        if isinstance(parsed, dict) and parsed.get("smoke") == "ok":
            _check("smoke json", True, str(parsed))
        return 0 if ok else 1
    except CursorAgentError as exc:
        _check("cursor live run", False, str(exc))
        return 1
    except Exception as exc:
        _check("cursor live run", False, str(exc))
        return 1


def _import_cursor_sdk() -> bool:
    try:
        import cursor_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test Cursor coding backend")
    parser.add_argument("--live", action="store_true", help="Call Cursor API (minimal read-only ping)")
    args = parser.parse_args()
    raise SystemExit(run_checks(live=args.live))


if __name__ == "__main__":
    main()
