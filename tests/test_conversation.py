"""Tests for multi-turn conversation helpers."""

import importlib.util
import sys
from pathlib import Path


def _load_conversation():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "conversation.py"
    name = "_conversation_test"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_conv = _load_conversation()
prepare_conversational_input = _conv.prepare_conversational_input
build_retrieval_query = _conv.build_retrieval_query
format_chat_history = _conv.format_chat_history


def _msgs(*pairs):
    return [{"role": role, "content": content} for role, content in pairs]


def test_follow_up_expands_retrieval_query():
    messages = _msgs(
        ("user", "dashboard nasıl silebilirimi?"),
        ("assistant", "Sağlanan bağlamda silme bilgisi yok."),
        ("user", "peki nasıl oluştururm"),
    )
    query = build_retrieval_query(messages)
    assert "dashboard" in query.lower()
    assert "oluştur" in query.lower()


def test_prepare_input_includes_history():
    messages = _msgs(
        ("user", "dashboard nasıl silebilirimi?"),
        ("assistant", "Silme bilgisi yok."),
        ("user", "peki nasıl oluştururm"),
    )
    prepared = prepare_conversational_input(messages)
    assert prepared["question"] == "peki nasıl oluştururm"
    assert "dashboard nasıl silebilirimi?" in prepared["chat_history"]
    assert "Silme bilgisi yok." in prepared["chat_history"]
    assert "dashboard" in prepared["retrieval_query"].lower()


def test_single_turn_has_no_prior_history():
    messages = _msgs(("user", "Dashboard nasıl oluşturabilirim?"))
    prepared = prepare_conversational_input(messages)
    assert prepared["question"] == "Dashboard nasıl oluşturabilirim?"
    assert prepared["chat_history"] == "(No prior conversation.)"
    assert prepared["retrieval_query"] == "Dashboard nasıl oluşturabilirim?"
