"""
Pivony Advisor Quality Loop — CrewAI crew runner.

Usage (from repo root, with venv + quality-loop deps installed):

    python -m quality_loop.crew
    python -m quality_loop.crew --iterations 5
    python -m quality_loop.crew --mode analyze --session sess_abc123

Environment: see quality_loop/README.md and .env.example (QUALITY_LOOP_*).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env from pivony-advisor root before CrewAI / LLM clients initialize.
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=False)

from crewai import Crew, Process

from quality_loop.agents import create_agents
from quality_loop.tasks import create_analyze_tasks, create_tasks

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def run_loop(iterations: int = 1) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(1, iterations + 1):
        print(f"\n{'=' * 60}")
        print(f"  QUALITY LOOP — İTERASYON {i}/{iterations}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}\n")

        cx_director, qa_agent, coding_agent = create_agents()
        conversation_task, qa_task, coding_task = create_tasks(
            cx_director, qa_agent, coding_agent
        )

        tasks = [t for t in (conversation_task, qa_task, coding_task) if t is not None]
        agents = [a for a in (cx_director, qa_agent, coding_agent) if a is not None]

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUT_DIR / f"iteration_{i}_{timestamp}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "iteration": i,
                    "timestamp": timestamp,
                    "result": str(result),
                    "pivony_advisor_url": os.environ.get(
                        "PIVONY_ADVISOR_URL", "http://127.0.0.1:8000"
                    ),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n[Loop] İterasyon {i} tamamlandı → {output_file}")

    print(f"\n[Loop] {iterations} iterasyon tamamlandı.")


def run_analyze(session_id: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _, qa_agent, coding_agent = create_agents()
    qa_task, coding_task = create_analyze_tasks(session_id, qa_agent, coding_agent)

    crew = Crew(
        agents=[qa_agent, coding_agent],
        tasks=[qa_task, coding_task],
        process=Process.sequential,
        verbose=True,
    )
    result = crew.kickoff()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"analyze_{session_id}_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {"session_id": session_id, "timestamp": timestamp, "result": str(result)},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n[Analyze] Tamamlandı → {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pivony Advisor Quality Loop")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--mode", choices=["full", "analyze"], default="full")
    parser.add_argument("--session", type=str, default=None)
    args = parser.parse_args()

    if args.mode == "analyze":
        if not args.session:
            parser.error("--mode analyze requires --session <session_id>")
        run_analyze(args.session)
    else:
        run_loop(iterations=args.iterations)


if __name__ == "__main__":
    main()
