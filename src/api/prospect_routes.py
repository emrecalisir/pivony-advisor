"""Sonic Prospect internal API routes (ingest + chat)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from prospect.config import SONIC_PROSPECT_RAG_SECRET
from prospect.ingest import ingest_bot_knowledge
from prospect.rag import answer_visitor_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/prospect", tags=["sonic-prospect"])


def _require_secret(provided: str | None) -> None:
    expected = SONIC_PROSPECT_RAG_SECRET
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SONIC_PROSPECT_RAG_SECRET is not configured",
        )
    if (provided or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ProspectIngestRequest(BaseModel):
    org_id: str = Field(..., min_length=1)
    bot_id: int
    bot_slug: str = ""
    language: str = "tr"
    faq_items: list[dict[str, Any]] = Field(default_factory=list)
    pdf_documents: list[dict[str, Any]] = Field(default_factory=list)


class ProspectChatRequest(BaseModel):
    org_id: str = Field(..., min_length=1)
    bot_id: int
    message: str = Field(..., min_length=1)
    system_prompt: str = ""
    language: str = "tr"
    chat_history: list[dict[str, str]] = Field(default_factory=list)


@router.post("/ingest")
async def prospect_ingest(
    request: ProspectIngestRequest,
    x_sonic_prospect_key: str | None = Header(default=None, alias="X-Sonic-Prospect-Key"),
) -> dict[str, Any]:
    _require_secret(x_sonic_prospect_key)
    try:
        result = ingest_bot_knowledge(request.model_dump())
        return {"ok": True, **result}
    except Exception as exc:
        logger.exception("Prospect ingest failed bot_id=%s: %s", request.bot_id, exc)
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc


@router.post("/chat")
async def prospect_chat(
    request: ProspectChatRequest,
    x_sonic_prospect_key: str | None = Header(default=None, alias="X-Sonic-Prospect-Key"),
) -> dict[str, Any]:
    _require_secret(x_sonic_prospect_key)
    try:
        return answer_visitor_question(
            org_id=request.org_id,
            bot_id=request.bot_id,
            message=request.message,
            system_prompt=request.system_prompt,
            language=request.language,
            chat_history=request.chat_history,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Prospect chat failed bot_id=%s: %s", request.bot_id, exc)
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc
