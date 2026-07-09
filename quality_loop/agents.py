"""CrewAI agent definitions for the Pivony Advisor quality loop."""

from __future__ import annotations

import os
from pathlib import Path

from crewai import Agent

from quality_loop.tools.advisor_tool import CreateSessionTool, PivonyAdvisorTool
from quality_loop.tools.db_tool import FetchRecentSessionsTool, FetchSessionTool
from quality_loop.tools.git_tool import (
    ApplyAndDeployTool,
    ListProjectFilesTool,
    ReadFileTool,
)

def _llm(env_key: str, default: str) -> str:
    return os.environ.get(env_key, default).strip() or default


def _resolve_sector(sector: str | None = None) -> str:
    return (sector or os.environ.get("QUALITY_LOOP_SECTOR") or "default").strip() or "default"


def create_agents(sector: str | None = None):
    from quality_loop.prompt_config import read_prompt

    resolved = _resolve_sector(sector)
    cx_persona = read_prompt("cx_director", resolved)["content"]
    qa_rubric = read_prompt("qa", resolved)["content"]

    cx_director = Agent(
        role="CX Director",
        goal=(
            "Pivony Advisor ile derinlemesine, gerçekçi bir analiz konuşması yap. "
            "Agent'ın zayıf noktalarını ortaya çıkar: bağlam kaybı, yanlış tool kullanımı, "
            "yetersiz yanıtlar. 6-10 tur konuş, her turda daha derin in."
        ),
        backstory=cx_persona,
        tools=[PivonyAdvisorTool(), CreateSessionTool()],
        llm=_llm("QUALITY_LOOP_CX_LLM", "gemini/gemini-2.0-flash"),
        verbose=True,
        allow_delegation=False,
        max_iter=15,
    )

    qa_agent = Agent(
        role="QA Agent",
        goal=(
            "Pivony Advisor'ın verdiği yanıtları objektif olarak değerlendir. "
            "Her sorunu kanıtıyla birlikte raporla. "
            "Coding Agent'ın direkt uygulayabileceği, dosya ve fonksiyon bazlı fix önerileri üret."
        ),
        backstory=(
            "Deneyimli bir QA mühendisisin. AI agent davranışlarını, "
            "tool call pattern'lerini ve conversation state yönetimini analiz etmekte uzmanlaşmışsın.\n\n"
            + qa_rubric
        ),
        tools=[FetchSessionTool(), FetchRecentSessionsTool()],
        llm=_llm("QUALITY_LOOP_QA_LLM", "anthropic/claude-sonnet-4-20250514"),
        verbose=True,
        allow_delegation=False,
    )

    coding_agent = Agent(
        role="Coding Agent",
        goal=(
            "QA Agent'ın raporundaki sorunları pivony-advisor Python projesinde düzelt. "
            "Önce ilgili dosyaları oku, sorunu anla, fix yaz. "
            "Git push ve deploy yalnızca QUALITY_LOOP_ALLOW_GIT_PUSH / QUALITY_LOOP_AUTO_DEPLOY açıksa."
        ),
        backstory=(
            "Kıdemli bir Python geliştiricisisin. AI agent sistemleri, "
            "tool call implementasyonu ve prompt engineering konusunda uzmanlaşmışsın. "
            "Değişiklik yapmadan önce mutlaka mevcut kodu okursun. "
            "Fix'lerin minimal, odaklı ve test edilebilir olmasına özen gösterirsin. "
            "Her commit mesajı '[quality-loop] <sorun özeti>' formatındadır."
        ),
        tools=[
            ReadFileTool(),
            ListProjectFilesTool(),
            ApplyAndDeployTool(),
        ],
        llm=_llm("QUALITY_LOOP_CODING_LLM", "anthropic/claude-sonnet-4-20250514"),
        verbose=True,
        allow_delegation=False,
        max_iter=20,
    )

    return cx_director, qa_agent, coding_agent
