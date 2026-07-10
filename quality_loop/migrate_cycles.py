"""Merge legacy outputs/runs/run_*.json QA data into unified session cycle files."""

from __future__ import annotations

import json
from pathlib import Path

from quality_loop.cycle_store import finalize_cycle, is_completed_cycle
from quality_loop.run_store import RUNS_DIR, _read_json
from quality_loop.session_store import SESSIONS_DIR, load_session


def migrate(*, dry_run: bool = False) -> dict[str, int]:
    stats = {"merged": 0, "skipped": 0, "orphan_runs": 0}
    if not RUNS_DIR.exists():
        return stats

    for path in sorted(RUNS_DIR.glob("run_*.json")):
        try:
            run = _read_json(path)
        except (ValueError, OSError, json.JSONDecodeError):
            stats["skipped"] += 1
            continue

        sid = str(run.get("session_id") or "")
        if not sid:
            stats["orphan_runs"] += 1
            continue

        session = load_session(sid)
        if session and is_completed_cycle(session):
            stats["skipped"] += 1
            continue

        if not session:
            stats["orphan_runs"] += 1
            continue

        patch = {
            "cycle_id": sid,
            "mode": run.get("mode"),
            "iteration": run.get("iteration"),
            "job_id": run.get("job_id"),
            "advisor_url": run.get("advisor_url"),
            "phases": run.get("phases"),
            "qa_report": run.get("qa_report"),
            "fixes": run.get("fixes"),
            "final_result": run.get("final_result"),
            "summary": run.get("summary"),
            "status": "done",
        }
        if not dry_run:
            finalize_cycle(sid, patch)
            # Mirror compat file with unified id (sess_*)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)
            mirror = RUNS_DIR / f"{safe}.json"
            from quality_loop.cycle_store import cycle_as_run

            payload = cycle_as_run(load_session(sid) or {})
            with open(mirror, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        stats["merged"] += 1

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate legacy runs into unified cycle sessions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
