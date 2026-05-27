"""FastAPI layer — OpenAI-compatible multi-tenant Pivony Advisor."""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from typing import Literal

# Allow imports from src/ (core, api, data packages live here)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from core.config import CREDS_PATH, DEFAULT_SECTOR, sector_slugify
from core.conversation import prepare_conversational_input
from core.followups import generate_followups
from core.rag import (
    build_embeddings,
    build_llm,
    build_rag_chain,
    create_qdrant_client,
    extract_api_system_prompt,
    invoke_advisor,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


def _prepare_chat_input(messages: list[ChatMessage]) -> dict[str, str]:
    try:
        return prepare_conversational_input(messages)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _openai_chat_completion(
    model: str,
    content: str,
    *,
    suggested_followups: list[str] | None = None,
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(message=ChatCompletionMessage(content=content))
        ],
        pivony_suggested_followups=suggested_followups or [],
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


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported")

    try:
        chat_input = _prepare_chat_input(request.messages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sector = sector_slugify(request.pivony_sector or DEFAULT_SECTOR)
    api_system = extract_api_system_prompt(request.messages)

    try:
        chain = _get_chain(sector, api_system)
        answer = chain.invoke(chat_input)
        followups = generate_followups(
            chat_input.get("retrieval_query") or chat_input["question"],
            answer,
            context_hint=api_system,
        )
        return _openai_chat_completion(
            request.model,
            answer,
            suggested_followups=followups,
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
async def advisor_query(request: QueryRequest) -> QueryResponse:
    sector = sector_slugify(request.sector)
    try:
        answer = invoke_advisor(request.question, sector_slug=sector)
        return QueryResponse(question=request.question, answer=answer, sector=sector)
    except Exception as exc:
        logger.exception("Advisor query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Advisor query failed: {exc}") from exc
