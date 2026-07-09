"""Tools that drive Pivony Advisor via POST /v1/chat/completions."""

from __future__ import annotations

import json
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from quality_loop.advisor_client import (
    build_page_context,
    chat,
    messages_for_api,
)
from quality_loop.session_store import (
    append_turn,
    create_session,
    load_session,
    update_session_context,
)


class AdvisorInput(BaseModel):
    session_id: str = Field(description="Quality-loop session ID (from create_advisor_session)")
    message: str = Field(description="User message to send to Pivony Advisor")
    dashboard_id: int | None = Field(
        default=None,
        description=(
            "When advisor shows a dashboard picker, pass the chosen dashboard id "
            "(e.g. 6208 for SURVEY) to lock scope for this and follow-up turns."
        ),
    )
    dashboard_name: str | None = Field(
        default=None,
        description="Display name for dashboard_id when simulating a picker selection.",
    )


class PivonyAdvisorTool(BaseTool):
    name: str = "pivony_advisor_chat"
    description: str = (
        "Send a user message to Pivony Advisor (POST /v1/chat/completions). "
        "Maintains multi-turn history in the quality-loop session store. "
        "If the prior response included a dashboard_picker, pass dashboard_id "
        "with the next message (or re-ask the pending question) to lock scope."
    )
    args_schema: Type[BaseModel] = AdvisorInput

    def _run(
        self,
        session_id: str,
        message: str,
        dashboard_id: int | None = None,
        dashboard_name: str | None = None,
    ) -> str:
        session = load_session(session_id)
        if session is None:
            return json.dumps({"error": f"unknown session_id: {session_id}"}, ensure_ascii=False)

        dashboard_selection = None
        if dashboard_id is not None:
            dashboard_selection = {
                "id": int(dashboard_id),
                "name": dashboard_name or f"Dashboard {dashboard_id}",
            }
            analytics_scope = {
                "dashboardId": int(dashboard_id),
                "orgWide": False,
            }
            session = update_session_context(
                session_id,
                analytics_scope=analytics_scope,
                last_dashboard_selection=dashboard_selection,
            )

        page_context = build_page_context(
            analytics_scope=session.get("analytics_scope"),
            dashboard_id=dashboard_id,
            dashboard_name=dashboard_name,
            last_dashboard_selection=session.get("last_dashboard_selection"),
        )

        history = list(session.get("messages") or [])
        history.append({"role": "user", "content": message})
        api_messages = messages_for_api(history)

        try:
            result = chat(
                api_messages,
                user_id=session.get("user_id"),
                user_email=session.get("user_email"),
                sector=session.get("sector") or "hospitality",
                advisor_mode=session.get("advisor_mode") or "advisor",
                page_context=page_context or None,
            )
        except Exception as exc:
            return json.dumps(
                {"error": str(exc), "session_id": session_id},
                ensure_ascii=False,
            )

        append_turn(
            session_id,
            user_content=message,
            assistant_content=result.get("content") or "",
            suggested_followups=result.get("suggested_followups"),
            guidance=result.get("guidance"),
            dashboard_picker=result.get("dashboard_picker"),
            reasoning=result.get("reasoning"),
            tool_actions=result.get("tool_actions"),
            dashboard_selection=dashboard_selection,
        )

        if dashboard_id is not None:
            update_session_context(
                session_id,
                page_context=page_context,
                analytics_scope=session.get("analytics_scope"),
                last_dashboard_selection=dashboard_selection,
            )

        payload: dict[str, Any] = {
            "session_id": session_id,
            "content": result.get("content"),
            "reasoning": result.get("reasoning"),
            "tool_actions": result.get("tool_actions"),
            "suggested_followups": result.get("suggested_followups"),
            "guidance": result.get("guidance"),
            "dashboard_picker": result.get("dashboard_picker"),
            "locked_dashboard_id": dashboard_id,
        }
        return json.dumps(payload, ensure_ascii=False)


class CreateSessionInput(BaseModel):
    user_id: str | None = Field(
        default=None,
        description="Firebase user id forwarded as pivony_user_id (optional)",
    )
    user_email: str | None = Field(
        default=None,
        description="User email forwarded to advisor (optional)",
    )
    sector: str = Field(default="hospitality", description="Sector slug, e.g. hospitality")
    advisor_mode: str = Field(
        default="advisor",
        description="advisor (freemium) or industry_expert",
    )


class CreateSessionTool(BaseTool):
    name: str = "create_advisor_session"
    description: str = (
        "Create a new quality-loop session (local JSON store). "
        "Returns session_id for pivony_advisor_chat."
    )
    args_schema: Type[BaseModel] = CreateSessionInput

    def _run(
        self,
        user_id: str | None = None,
        user_email: str | None = None,
        sector: str = "hospitality",
        advisor_mode: str = "advisor",
    ) -> str:
        import os

        env_uid = os.environ.get("QUALITY_LOOP_USER_ID", "").strip()
        env_email = os.environ.get("QUALITY_LOOP_USER_EMAIL", "").strip()
        env_sector = os.environ.get("QUALITY_LOOP_SECTOR", "").strip()
        effective_user_id = env_uid or user_id
        effective_user_email = env_email or user_email
        effective_sector = env_sector or sector or "hospitality"

        session = create_session(
            user_id=effective_user_id,
            user_email=effective_user_email,
            sector=effective_sector,
            advisor_mode=advisor_mode,
        )
        return json.dumps(
            {
                "session_id": session["session_id"],
                "note": (
                    "Advisor is stateless; history is kept in quality_loop/outputs/sessions/. "
                    "Use pivony_advisor_chat for each turn."
                ),
            },
            ensure_ascii=False,
        )
