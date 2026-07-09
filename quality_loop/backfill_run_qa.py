"""Backfill qa_report/fixes on run JSON files where phase raw_output failed to parse."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from quality_loop.run_store import RUNS_DIR, _fixes_from_phases, _qa_from_phases
from quality_loop.fix_snapshots import enrich_fixes

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    paths = [target] if target else sorted(RUNS_DIR.glob("run_*.json"))
    updated = 0
    for path in paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        phases = data.get("phases") or []
        qa = _qa_from_phases(phases)
        fixes = enrich_fixes(_fixes_from_phases(phases), job_id=data.get("job_id"))
        enriched_same = (
            qa == data.get("qa_report")
            and json.dumps(fixes, sort_keys=True) == json.dumps(data.get("fixes"), sort_keys=True)
        )
        if enriched_same:
            continue
        data["qa_report"] = qa
        data["fixes"] = fixes
        summary = data.get("summary") or {}
        summary["verdict"] = (qa or {}).get("overall_verdict") if isinstance(qa, dict) else None
        summary["issue_count"] = len((qa or {}).get("issues") or []) if isinstance(qa, dict) else 0
        summary["fixes_applied"] = len((fixes or {}).get("fixes_applied") or []) if isinstance(fixes, dict) else 0
        summary["fixes_skipped"] = len((fixes or {}).get("fixes_skipped") or []) if isinstance(fixes, dict) else 0
        data["summary"] = summary
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
        print(f"updated {path.name} verdict={summary.get('verdict')} issues={summary.get('issue_count')}")
    print(f"done: {updated} file(s)")
