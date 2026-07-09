"""CrewAI architecture metadata for the UI (no CrewAI import required)."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent


def get_architecture() -> dict:
    return {
        "framework": "CrewAI",
        "process": "sequential",
        "description": (
            "Pivony Advisor Quality Loop — üç ajan sırayla çalışır. "
            "CX Director Advisor'ı test eder, QA Agent kalite kararını verir, "
            "Coding Agent iyileştirmeyi uygular."
        ),
        "layers": [
            {
                "id": "advisor",
                "title": "Pivony Advisor",
                "subtitle": "Test edilen sistem",
                "endpoint": os.environ.get("PIVONY_ADVISOR_URL", "http://127.0.0.1:8011"),
                "api": "POST /v1/chat/completions",
                "state": "stateless — session quality_loop/outputs/sessions/ altında",
            },
            {
                "id": "orchestration",
                "title": "quality_loop/",
                "subtitle": "CrewAI orchestration",
                "path": str(_PACKAGE_ROOT),
                "runner": "python -m quality_loop.crew",
                "venv": ".venv-quality-loop (Python 3.12)",
            },
            {
                "id": "storage",
                "title": "Outputs",
                "subtitle": "Şeffaf kayıt",
                "paths": {
                    "sessions": "quality_loop/outputs/sessions/*.json",
                    "runs": "quality_loop/outputs/runs/run_*.json",
                    "jobs": "quality_loop/outputs/jobs/job_*.json",
                },
            },
            {
                "id": "langsmith",
                "title": "LangSmith",
                "subtitle": "Runtime trace — agent reasoning, tool calls, token/cost",
                "docs": "https://docs.langchain.com/langsmith/trace-with-crewai",
                "env": ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT"],
            },
        ],
        "agents": [
            {
                "id": "cx_director",
                "role": "CX Director",
                "llm_env": "QUALITY_LOOP_CX_LLM",
                "llm_default": "gemini/gemini-2.0-flash",
                "goal": "Advisor ile 6-10 tur gerçekçi analiz konuşması; zayıf noktaları ortaya çıkar",
                "tools": [
                    {"name": "create_advisor_session", "desc": "Yeni session oluşturur"},
                    {"name": "pivony_advisor_chat", "desc": "Advisor'a mesaj gönderir, SSE yanıt yakalar"},
                ],
                "outputs": ["session_id", "conversation_summary", "notable_issues"],
            },
            {
                "id": "qa_agent",
                "role": "QA Agent (Quality Checker)",
                "llm_env": "QUALITY_LOOP_QA_LLM",
                "llm_default": "anthropic/claude-sonnet-4-20250514",
                "goal": "Rubric'e göre değerlendirme — Advisor nerede gelişmeli kararını VERİR",
                "tools": [
                    {"name": "fetch_conversation", "desc": "Session mesajlarını okur"},
                    {"name": "fetch_recent_sessions", "desc": "Son session listesi"},
                ],
                "outputs": ["scores", "issues", "overall_verdict", "priority_fix", "fix_hint"],
                "decision_maker": True,
                "prompt_file": "config/qa_rubric.txt",
                "prompt_agent_id": "qa",
            },
            {
                "id": "coding_agent",
                "role": "Coding Agent",
                "llm_env": "QUALITY_LOOP_CODING_LLM",
                "llm_default": "anthropic/claude-sonnet-4-20250514",
                "goal": "QA raporundaki fix_hint'lere göre pivony-advisor kodunu düzeltir",
                "tools": [
                    {"name": "read_project_file", "desc": "Kaynak dosya okur"},
                    {"name": "list_project_files", "desc": "Proje yapısı"},
                    {"name": "apply_fix_and_deploy", "desc": "Fix yazar (git/deploy env flag)"},
                ],
                "outputs": ["fixes_applied", "fixes_skipped", "next_test_scenarios"],
            },
        ],
        "tasks": [
            {
                "id": "conversation_task",
                "agent": "CX Director",
                "phase": "conversation",
                "context": [],
                "scenarios": [
                    "Dashboard seçimi ve bağlam",
                    "list_reviews",
                    "get_topic_trends",
                    "get_pivony_metrics",
                    "get_root_causes",
                ],
            },
            {
                "id": "qa_task",
                "agent": "QA Agent",
                "phase": "qa",
                "context": ["conversation_task"],
                "rubric": "config/qa_rubric.txt (sector override: config/sectors/<sector>/qa_rubric.txt)",
                "editable": True,
            },
            {
                "id": "coding_task",
                "agent": "Coding Agent",
                "phase": "coding",
                "context": ["qa_task"],
            },
        ],
        "flow": [
            {"from": "CX Director", "to": "Pivony Advisor", "via": "pivony_advisor_chat", "label": "6-10 tur"},
            {"from": "CX Director", "to": "QA Agent", "via": "session_id + conversation output", "label": "context"},
            {"from": "QA Agent", "to": "Coding Agent", "via": "qa_report + fix_hint", "label": "karar"},
            {"from": "Coding Agent", "to": "pivony-advisor repo", "via": "apply_fix_and_deploy", "label": "fix"},
        ],
        "llm_config": {
            "QUALITY_LOOP_CX_LLM": os.environ.get("QUALITY_LOOP_CX_LLM", "gemini/gemini-2.0-flash"),
            "QUALITY_LOOP_QA_LLM": os.environ.get("QUALITY_LOOP_QA_LLM", "anthropic/claude-sonnet-4-20250514"),
            "QUALITY_LOOP_CODING_LLM": os.environ.get("QUALITY_LOOP_CODING_LLM", "anthropic/claude-sonnet-4-20250514"),
        },
        "repo_root": os.environ.get("PIVONY_REPO_ROOT", str(_REPO_ROOT)),
        "observability": {
            "provider": "LangSmith",
            "role": "Runtime trace — agent reasoning, tool calls, token/cost tree",
            "docs": "https://docs.langchain.com/langsmith/trace-with-crewai",
            "env": ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "QUALITY_LOOP_LANGSMITH_ENABLED"],
        },
    }
