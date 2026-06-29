"""FastAPI layer — OpenAI-compatible multi-tenant Pivony Advisor."""

from __future__ import annotations

import json
import logging
import asyncio
import os
import sys
import time
import uuid
from typing import Literal

# Allow imports from src/ (core, api, data packages live here)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from core.agent import DEFAULT_ADVISOR_MODE, run_advisor_agent
from core.config import (
    CREDS_PATH,
    DEFAULT_SECTOR,
    USE_AGENT,
    USE_VERTEX_CONTEXTUAL_NAVIGATION,
    sector_slugify,
)
from core.llm_resilience import (
    GENERIC_LLM_ERROR_MESSAGE,
    LlmTurnFailed,
    is_terminal_llm_user_message,
)
from core.conversation import extract_turns, prepare_conversational_input
from core.agent_stream import stream_advisor_agent, stream_simple_completion
from core.contextual_navigation import generate_contextual_navigation
from core.logging_config import get_advisor_logger, log_conversation, setup_logging
from core.rag import (
    build_embeddings,
    build_llm,
    build_rag_chain,
    create_qdrant_client,
    extract_api_system_prompt,
    invoke_advisor,
)

setup_logging()
logger = get_advisor_logger("api")

if not os.path.exists(CREDS_PATH):
    logger.error("google_creds.json not found at %s", CREDS_PATH)
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

DEFAULT_OPENAI_MODEL = "pivony-local-llm"

CORS_ALLOW_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOW_ORIGINS",
        "https://app.pivony.com,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# Shared clients (lazy chain cache per sector)
_embeddings = None
_qdrant_client = None
_llm = None
_chain_cache: dict[str, Runnable] = {}


def _components():
    global _embeddings, _qdrant_client, _llm
    if _embeddings is None:
        _embeddings = build_embeddings()
        _qdrant_client = create_qdrant_client()
        _llm = build_llm()
    return _embeddings, _qdrant_client, _llm


def _get_chain(sector_slug: str, extra_system_prompt: str | None = None) -> Runnable:
    slug = sector_slugify(sector_slug or DEFAULT_SECTOR)
    cache_key = f"{slug}::{hash(extra_system_prompt or '')}"
    if cache_key in _chain_cache:
        return _chain_cache[cache_key]

    embeddings, client, llm = _components()
    chain = build_rag_chain(
        sector_slug=slug,
        llm=llm,
        embeddings=embeddings,
        client=client,
        extra_system_prompt=extra_system_prompt,
    )
    _chain_cache[cache_key] = chain
    return chain


app = FastAPI(title="Pivony Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    sector: str = Field(default=DEFAULT_SECTOR, description="Industry slug, e.g. hospitality")
    pivony_user_id: str | None = Field(default=None)
    pivony_user_email: str | None = Field(default=None)


class QueryResponse(BaseModel):
    question: str
    answer: str
    sector: str


class HealthResponse(BaseModel):
    status: str


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "function"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default=DEFAULT_OPENAI_MODEL)
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False
    pivony_sector: str | None = Field(
        default=None,
        description="Industry slug for sector RAG + sector prompt (from pivony-api)",
    )
    pivony_user_id: str | None = Field(
        default=None,
        description="Firebase user id (from pivony-api)",
    )
    pivony_user_email: str | None = Field(
        default=None,
        description="User email (from pivony-api)",
    )
    pivony_page_context: dict | None = Field(
        default=None,
        description=(
            "Structured page scope from pivony-api (dashboard_id, since, until) so "
            "tools can be pinned to exactly what the user's page is showing."
        ),
    )
    pivony_advisor_mode: str | None = Field(
        default=None,
        description=(
            "Product tier from pivony-api: 'industry_expert' (paid, raw-review RAG) "
            "or 'advisor' (freemium, metrics-only). Defaults to industry_expert."
        ),
    )


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: Literal["stop"] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    pivony_suggested_followups: list[str] = Field(default_factory=list)
    pivony_guidance: str = Field(
        default="",
        description="Cursor-style contextual next-step guidance prose",
    )
    pivony_dashboard_picker: dict | None = Field(
        default=None,
        description="When set, the UI should render a searchable dashboard picker: {dashboards:[{id,name}], default_dashboard_id}",
    )
    pivony_charts: list[dict] = Field(
        default_factory=list,
        description="Welcome-compatible chart payloads rendered inline with the assistant reply.",
    )


def _prepare_chat_input(messages: list[ChatMessage]) -> dict[str, str]:
    try:
        return prepare_conversational_input(messages)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _resolve_user_context(
    request: ChatCompletionRequest | QueryRequest,
    http_request: Request | None = None,
) -> tuple[str | None, str | None]:
    user_id = getattr(request, "pivony_user_id", None)
    user_email = getattr(request, "pivony_user_email", None)
    if http_request is not None:
        if not user_id:
            user_id = http_request.headers.get("x-pivony-user-id")
        if not user_email:
            user_email = http_request.headers.get("x-pivony-user-email")
    return (
        str(user_id).strip() if user_id else None,
        str(user_email).strip() if user_email else None,
    )


def _messages_for_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in ("user", "assistant") and message.content
    ]


def _openai_chat_completion(
    model: str,
    content: str,
    *,
    suggested_followups: list[str] | None = None,
    guidance: str | None = None,
    dashboard_picker: dict | None = None,
    charts: list[dict] | None = None,
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(message=ChatCompletionMessage(content=content))
        ],
        pivony_suggested_followups=suggested_followups or [],
        pivony_guidance=guidance or "",
        pivony_dashboard_picker=dashboard_picker,
        pivony_charts=charts or [],
    )


@app.on_event("startup")
async def startup() -> None:
    try:
        _components()
        logger.info("Advisor components initialized.")
    except Exception as exc:
        logger.exception("Startup failed: %s", exc)
        raise


@app.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_OPENAI_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "pivony",
            }
        ],
    }


def _sse_payload(data: object) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat_events(
    request: ChatCompletionRequest,
    *,
    user_id: str | None,
    user_email: str | None,
    chat_input: dict[str, str],
    sector: str,
    api_system: str | None,
    advisor_mode: str,
):
    embeddings, client, llm = _components()
    turns = extract_turns(request.messages)
    answer = ""
    dashboard_picker: dict | None = None
    charts: list[dict] = []

    if USE_AGENT:
        stream = stream_advisor_agent(
            turns=turns,
            sector_slug=sector,
            extra_system_prompt=api_system,
            embeddings=embeddings,
            client=client,
            advisor_mode=advisor_mode,
            user_id=user_id,
            page_context=request.pivony_page_context,
        )
    else:
        stream = stream_simple_completion(
            system_prompt=api_system or "",
            user_messages=turns,
        )

    try:
        for event in stream:
            if event.get("type") == "done":
                answer = str(event.get("content") or "")
                dashboard_picker = event.get("dashboard_picker")
                raw_charts = event.get("charts")
                if isinstance(raw_charts, list):
                    charts = [c for c in raw_charts if isinstance(c, dict)]
                continue
            if event.get("type") == "dashboard_picker":
                picker_payload = event.get("picker")
                if isinstance(picker_payload, dict):
                    dashboard_picker = picker_payload
                yield _sse_payload(event)
                await asyncio.sleep(0)
                continue
            yield _sse_payload(event)
            await asyncio.sleep(0)
    except LlmTurnFailed as exc:
        answer = exc.user_message
        yield _sse_payload(
            {"type": "content", "delta": exc.user_message, "replace": True}
        )
    except Exception as exc:
        logger.error("Advisor stream failed: %s", exc, exc_info=True)
        answer = GENERIC_LLM_ERROR_MESSAGE
        yield _sse_payload(
            {"type": "content", "delta": answer, "replace": True}
        )

    if dashboard_picker or is_terminal_llm_user_message(answer):
        followups, guidance = [], ""
    else:
        followups, guidance = generate_contextual_navigation(
            chat_input.get("retrieval_query") or chat_input["question"],
            answer,
            chat_history=chat_input.get("chat_history"),
            context_hint=api_system,
            llm=llm,
            use_vertex=USE_VERTEX_CONTEXTUAL_NAVIGATION,
        )
    log_conversation(
        user_id=user_id,
        user_email=user_email,
        sector=sector,
        model=request.model,
        messages=_messages_for_history(request.messages),
        assistant_response=answer,
        suggested_followups=followups,
        guidance=guidance,
    )
    yield _sse_payload(
        {
            "type": "done",
            "content": answer,
            "pivony_suggested_followups": followups,
            "pivony_guidance": guidance,
            "pivony_dashboard_picker": dashboard_picker,
            "pivony_charts": charts,
        }
    )
    yield "data: [DONE]\n\n"
    await asyncio.sleep(0)


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
):
    user_id, user_email = _resolve_user_context(request, http_request)

    try:
        chat_input = _prepare_chat_input(request.messages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sector = sector_slugify(request.pivony_sector or DEFAULT_SECTOR)
    api_system = extract_api_system_prompt(request.messages)
    advisor_mode = (request.pivony_advisor_mode or DEFAULT_ADVISOR_MODE).strip().lower()

    logger.info(
        "chat_completions user_id=%s user_email=%s sector=%s model=%s messages=%s agent=%s mode=%s stream=%s",
        user_id or "-",
        user_email or "-",
        sector,
        request.model,
        len(request.messages),
        USE_AGENT,
        advisor_mode,
        request.stream,
    )

    if request.stream:
        try:
            return StreamingResponse(
                _stream_chat_events(
                    request,
                    user_id=user_id,
                    user_email=user_email,
                    chat_input=chat_input,
                    sector=sector,
                    api_system=api_system,
                    advisor_mode=advisor_mode,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Streaming chat completion failed: %s", exc)
            raise HTTPException(
                status_code=500, detail=f"Chat completion failed: {exc}"
            ) from exc

    try:
        embeddings, client, llm = _components()
        dashboard_picker: dict | None = None
        if USE_AGENT:
            answer, dashboard_picker = run_advisor_agent(
                turns=extract_turns(request.messages),
                sector_slug=sector,
                extra_system_prompt=api_system,
                embeddings=embeddings,
                client=client,
                llm=llm,
                advisor_mode=advisor_mode,
                user_id=user_id,
                page_context=request.pivony_page_context,
            )
        else:
            chain = _get_chain(sector, api_system)
            answer = chain.invoke(chat_input)
        if dashboard_picker:
            followups, guidance = [], ""
        else:
            followups, guidance = generate_contextual_navigation(
                chat_input.get("retrieval_query") or chat_input["question"],
                answer,
                chat_history=chat_input.get("chat_history"),
                context_hint=api_system,
                llm=llm,
                use_vertex=USE_VERTEX_CONTEXTUAL_NAVIGATION,
            )
        log_conversation(
            user_id=user_id,
            user_email=user_email,
            sector=sector,
            model=request.model,
            messages=_messages_for_history(request.messages),
            assistant_response=answer,
            suggested_followups=followups,
            guidance=guidance,
        )
        return _openai_chat_completion(
            request.model,
            answer,
            suggested_followups=followups,
            guidance=guidance,
            dashboard_picker=dashboard_picker,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chat completion failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Chat completion failed: {exc}") from exc


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy")


@app.get("/", response_model=HealthResponse)
async def root() -> HealthResponse:
    return HealthResponse(status="healthy")


@app.post("/api/v1/advisor/query", response_model=QueryResponse)
async def advisor_query(
    request: QueryRequest,
    http_request: Request,
) -> QueryResponse:
    sector = sector_slugify(request.sector)
    user_id, user_email = _resolve_user_context(request, http_request)
    try:
        answer = invoke_advisor(request.question, sector_slug=sector)
        _, _, llm = _components()
        followups, guidance = generate_contextual_navigation(
            request.question,
            answer,
            llm=llm,
            use_vertex=USE_VERTEX_CONTEXTUAL_NAVIGATION,
        )
        log_conversation(
            user_id=user_id,
            user_email=user_email,
            sector=sector,
            model="advisor-query",
            messages=[{"role": "user", "content": request.question}],
            assistant_response=answer,
            suggested_followups=followups,
            guidance=guidance,
            endpoint="/api/v1/advisor/query",
        )
        return QueryResponse(question=request.question, answer=answer, sector=sector)
    except Exception as exc:
        logger.exception("Advisor query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Advisor query failed: {exc}") from exc
