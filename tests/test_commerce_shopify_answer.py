"""Tests for Sonic Prospect Commerce (Shopify) generation."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from commerce_shopify import answer as commerce_answer

BLOCKS = [
    {
        "kind": "product",
        "title": "The Collection Snowboard: Liquid",
        "url": "https://demo.myshopify.com/products/liquid-snowboard",
        "text": "Price 749.95 USD. In stock.",
        "fresh_at": "2026-09-12T10:00:00.000Z",
    },
    {
        "kind": "policy",
        "title": "Privacy Policy",
        "url": "https://demo.myshopify.com/policies/privacy-policy",
        "text": "We keep order data for seven years.",
    },
]


def _stub_llm(captured: dict) -> Any:
    """Stand in for ChatGoogleGenerativeAI without contacting Vertex AI."""

    def factory(**kwargs):
        captured.update(kwargs)

        def respond(prompt_value):
            captured["messages"] = prompt_value.to_messages()
            return AIMessage(
                content="The Liquid snowboard is in stock at 749.95 USD.",
                usage_metadata={
                    "input_tokens": 120,
                    "output_tokens": 14,
                    "total_tokens": 134,
                },
                response_metadata={"finish_reason": "STOP"},
            )

        return RunnableLambda(respond)

    return factory


def test_answer_uses_caller_context_and_system_prompt(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        commerce_answer, "ChatGoogleGenerativeAI", _stub_llm(captured)
    )

    result = commerce_answer.answer_commerce_question(
        shop_domain="demo.myshopify.com",
        message="is the liquid snowboard in stock?",
        system_prompt="You are the shop assistant for demo.myshopify.com.",
        context_blocks=BLOCKS,
        chat_history=[{"role": "user", "content": "hi"}],
    )

    assert result["answer"] == "The Liquid snowboard is in stock at 749.95 USD."
    assert result["usage"] == {"input_tokens": 120, "output_tokens": 14}
    assert result["finish_reason"] == "stop"
    assert result["blocks_used"] == 2
    assert result["model"] == commerce_answer.COMMERCE_LLM_MODEL

    system, human = captured["messages"]
    assert system.content == "You are the shop assistant for demo.myshopify.com."
    assert "The Collection Snowboard: Liquid" in human.content
    assert "(read 2026-09-12T10:00:00.000Z)" in human.content
    assert "user: hi" in human.content
    assert "is the liquid snowboard in stock?" in human.content


def test_answer_runs_on_vertex_with_project_config(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        commerce_answer, "ChatGoogleGenerativeAI", _stub_llm(captured)
    )

    commerce_answer.answer_commerce_question(
        shop_domain="demo.myshopify.com",
        message="hello",
        system_prompt="System.",
    )

    assert captured["vertexai"] is True
    assert captured["model"] == commerce_answer.COMMERCE_LLM_MODEL
    assert captured["project"]
    assert captured["location"]


def test_answer_requires_message_and_system_prompt(monkeypatch):
    monkeypatch.setattr(commerce_answer, "ChatGoogleGenerativeAI", _stub_llm({}))

    with pytest.raises(ValueError):
        commerce_answer.answer_commerce_question(
            shop_domain="demo.myshopify.com", message="   ", system_prompt="System."
        )
    with pytest.raises(ValueError):
        commerce_answer.answer_commerce_question(
            shop_domain="demo.myshopify.com", message="hello", system_prompt=" "
        )


def test_context_placeholder_when_nothing_retrieved():
    assert commerce_answer._format_context([]) == "(No store context available.)"
    assert (
        commerce_answer._format_context([{"kind": "product", "text": "  "}])
        == "(No store context available.)"
    )


def test_context_is_capped():
    blocks = [{"kind": "product", "text": f"body {i}"} for i in range(20)]
    rendered = commerce_answer._format_context(blocks)
    assert "body 11" in rendered
    assert "body 12" not in rendered


def test_history_keeps_last_turns_only():
    history = [{"role": "user", "content": f"turn {i}"} for i in range(12)]
    rendered = commerce_answer._format_history(history)
    assert "turn 11" in rendered
    assert "turn 3" not in rendered
    assert commerce_answer._format_history([]) == "(No prior messages.)"


def test_message_text_joins_chunked_parts():
    assert (
        commerce_answer._message_text([{"text": "Half "}, {"text": "answer."}])
        == "Half answer."
    )
