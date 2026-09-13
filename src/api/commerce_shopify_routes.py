"""Sonic Prospect Commerce internal API for the Shopify vertical."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from commerce_shopify.answer import COMMERCE_SECRET, answer_commerce_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/commerce-shopify", tags=["sonic-prospect-commerce"])


def _require_secret(provided: str | None) -> None:
    if not COMMERCE_SECRET:
        logger.error("Commerce answer refused: SONIC_COMMERCE_SECRET is not configured")
        raise HTTPException(
            status_code=503, detail="SONIC_COMMERCE_SECRET is not configured"
        )
    if (provided or "").strip() != COMMERCE_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ContextBlock(BaseModel):
    kind: str = "context"
    title: str | None = None
    url: str | None = None
    text: str = ""
    fresh_at: str | None = None


class CommerceAnswerRequest(BaseModel):
    shop_domain: str = Field(..., min_length=1)
    session_id: str = ""
    language: str = "en"
    system_prompt: str = Field(..., min_length=1)
    context_blocks: list[ContextBlock] = Field(default_factory=list)
    message: str = Field(..., min_length=1)
    history: list[dict[str, str]] = Field(default_factory=list)


@router.post("/answer")
async def commerce_answer(
    request: CommerceAnswerRequest,
    x_commerce_key: str | None = Header(default=None, alias="X-Commerce-Key"),
) -> dict[str, Any]:
    _require_secret(x_commerce_key)
    try:
        result = answer_commerce_question(
            shop_domain=request.shop_domain,
            message=request.message,
            system_prompt=request.system_prompt,
            context_blocks=[block.model_dump() for block in request.context_blocks],
            chat_history=request.history,
        )
        logger.info(
            "Commerce answer ok shop=%s session=%s language=%s blocks=%s model=%s "
            "input_tokens=%s output_tokens=%s",
            request.shop_domain,
            request.session_id,
            request.language,
            result.get("blocks_used"),
            result.get("model"),
            result.get("usage", {}).get("input_tokens"),
            result.get("usage", {}).get("output_tokens"),
        )
        return result
    except ValueError as exc:
        logger.warning(
            "Commerce answer rejected shop=%s: %s", request.shop_domain, exc
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Commerce answer failed shop=%s: %s", request.shop_domain, exc
        )
        raise HTTPException(status_code=500, detail=f"Answer failed: {exc}") from exc
