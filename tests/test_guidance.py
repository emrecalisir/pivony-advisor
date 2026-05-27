"""Tests for contextual guidance prose."""

import importlib.util
import sys
from pathlib import Path


def _load_guidance():
    path = Path(__file__).resolve().parents[1] / "src" / "core" / "guidance.py"
    name = "_guidance_test"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.generate_contextual_guidance


generate_contextual_guidance = _load_guidance()


def test_single_topic_guidance():
    text = generate_contextual_guidance(
        ["Dashboard nasıl oluşturabilirim?"]
    )
    assert "İstersen bir sonraki adımda" in text
    assert "dashboard" in text.lower()


def test_multi_topic_guidance():
    text = generate_contextual_guidance(
        [
            "İç veriyi nasıl analiz ederim?",
            "AI Insights raporu nasıl alınır?",
            "My Workspace'e KPI widget'ı nasıl eklerim?",
        ]
    )
    assert "İstersen bir sonraki adımda" in text
    assert "veya" in text
