"""Tests for hard agent state resolution and tool routing."""

import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, rel_path: str):
    path = Path(__file__).resolve().parents[1] / "src" / "core" / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_analytics = _load_module(
    "core.analytics_scope",
    "analytics_scope.py",
)
if "core" not in sys.modules:
    sys.modules["core"] = type(sys)("core")
sys.modules["core.analytics_scope"] = _analytics

_agent_state = _load_module(
    "core.agent_state",
    "agent_state.py",
)
if "core" not in sys.modules:
    sys.modules["core"] = type(sys)("core")
sys.modules["core.analytics_scope"] = _analytics

_fake_platform = type(sys)("core.pivony_platform")
_fake_platform.fetch_pivots = lambda *a, **k: None
sys.modules["core.pivony_platform"] = _fake_platform

_pivot_resolve = _load_module(
    "core.pivot_resolve",
    "pivot_resolve.py",
)
sys.modules["core.pivot_resolve"] = _pivot_resolve

_tool_routing = _load_module(
    "core.tool_routing",
    "tool_routing.py",
)

resolve_hard_agent_state = _agent_state.resolve_hard_agent_state
hard_context_prompt_block = _agent_state.hard_context_prompt_block
HardAgentState = _agent_state.HardAgentState
should_expose_list_dashboards = _tool_routing.should_expose_list_dashboards
sanitize_tool_calls = _tool_routing.sanitize_tool_calls
pin_tool_args_for_state = _tool_routing.pin_tool_args_for_state
_DASHBOARD_ARG_TOOLS = _tool_routing._DASHBOARD_ARG_TOOLS

_NEW_DASHBOARD_TOOLS = frozenset(
    {
        "get_topic_intent_distribution",
        "get_topic_sentiment",
        "get_topic_participation",
        "get_key_drivers",
        "get_digital_experience_score",
        "get_stored_genai_insights",
    }
)


def test_locked_dashboard_from_page_context():
    state = resolve_hard_agent_state(
        [("user", "kaç yorum var")],
        {"dashboard_id": 6208, "since": "2026-06-01", "until": "2026-06-08"},
    )
    assert state.dashboard_id == 6208
    assert state.dashboard_locked is True
    assert should_expose_list_dashboards(state) is False


def test_selected_days_range_maps_to_hard_state_days():
    state = resolve_hard_agent_state(
        [("user", "NPS trendi")],
        {"selectedDaysRange": 7, "since": "2026-06-09", "until": "2026-06-16"},
    )
    assert state.days == 7
    assert state.since == "2026-06-09"


def test_dashboard_selection_from_picker():
    state = resolve_hard_agent_state(
        [("user", "NPS trendi")],
        {"dashboard_selection": {"id": 6208, "name": "SURVEY"}},
    )
    assert state.dashboard_id == 6208
    assert state.dashboard_locked is True
    assert state.source == "dashboard_selection"


def test_analytics_scope_dashboard_is_locked():
    state = resolve_hard_agent_state(
        [("user", "şikayet konuları")],
        {"analytics_scope": {"dashboard_id": 6208, "org_wide": False}},
    )
    assert state.dashboard_id == 6208
    assert state.dashboard_locked is True
    block = hard_context_prompt_block(state)
    assert "list_dashboards" in block
    assert "6208" in block


def test_org_wide_analytics_scope_defers_to_last_dashboard_selection():
    state = resolve_hard_agent_state(
        [("user", "örnek yorumlar")],
        {
            "analytics_scope": {"org_wide": True, "days": 7},
            "last_dashboard_selection": {"id": 6208, "name": "SURVEY"},
        },
    )
    assert state.dashboard_id == 6208
    assert state.dashboard_locked is True
    assert state.org_wide is False
    assert state.source == "last_dashboard_selection"
    assert should_expose_list_dashboards(state) is False


def test_org_wide_analytics_scope_defers_to_page_dashboard_id():
    state = resolve_hard_agent_state(
        [("user", "grafiği tekrar oluştur")],
        {
            "analytics_scope": {"org_wide": True, "days": 7},
            "dashboard_id": 6208,
        },
    )
    assert state.dashboard_id == 6208
    assert state.dashboard_locked is True
    assert state.org_wide is False
    assert state.source == "page_dashboard_id"


def test_fresh_session_has_no_inherited_dashboard():
    state = resolve_hard_agent_state(
        [("user", "Bu konuların duygu trendleri nasıl?")],
        {
            "fresh_session": True,
            "dashboard_id": 6208,
            "analytics_scope": {"org_wide": True, "days": 7},
            "last_dashboard_selection": {"id": 6208, "name": "SURVEY"},
        },
    )
    assert state.dashboard_id is None
    assert state.org_wide is False
    assert state.source == "fresh_session"
    assert should_expose_list_dashboards(state) is True
    block = hard_context_prompt_block(state)
    assert "brand-new chat" in block


def test_fresh_session_honours_picker_selection_on_same_turn():
    state = resolve_hard_agent_state(
        [("user", "Bu konuların duygu trendleri nasıl?")],
        {
            "fresh_session": True,
            "dashboard_selection": {"id": 6525, "name": "etstur memnuniyet"},
        },
    )
    assert state.dashboard_id == 6525
    assert state.dashboard_locked is True
    assert state.source == "dashboard_selection"


def test_sanitize_drops_list_dashboards_when_scope_set():
    state = HardAgentState(dashboard_id=6208, dashboard_locked=True, source="test")
    calls = [
        {"name": "list_dashboards", "args": {}},
        {"name": "get_pivony_metrics", "args": {"days": 7}},
    ]
    sanitized = sanitize_tool_calls(calls, state)
    assert len(sanitized) == 1
    assert sanitized[0]["name"] == "get_pivony_metrics"


def test_pin_tool_args_strips_model_guessed_dashboard_id():
    state = HardAgentState(source="none")
    args = pin_tool_args_for_state(
        "get_trends",
        {"dashboard_id": 6208, "days": 7},
        state,
    )
    assert "dashboard_id" not in args


def test_pin_tool_args_injects_user_selected_dashboard_id():
    state = HardAgentState(
        dashboard_id=6208,
        dashboard_locked=True,
        source="dashboard_selection",
    )
    args = pin_tool_args_for_state(
        "get_trends",
        {"dashboard_id": 9999, "days": 7, "org_wide": True},
        state,
    )
    assert args["dashboard_id"] == 6208
    assert "org_wide" not in args


def test_pin_tool_args_sets_org_wide_for_metrics():
    state = HardAgentState(org_wide=True, days=7, source="analytics_scope_org_wide")
    args = pin_tool_args_for_state(
        "get_pivony_metrics",
        {"days": 7},
        state,
    )
    assert "dashboard_id" not in args
    assert args["org_wide"] is True


def test_pin_tool_args_strips_org_wide_from_dashboard_tools():
    state = HardAgentState(
        dashboard_id=6208,
        dashboard_locked=True,
        source="dashboard_selection",
    )
    args = pin_tool_args_for_state(
        "get_trends",
        {"days": 7, "org_wide": True},
        state,
    )
    assert args["dashboard_id"] == 6208
    assert "org_wide" not in args


def test_pin_tool_args_strips_org_wide_when_scope_unresolved():
    state = HardAgentState(source="none")
    args = pin_tool_args_for_state(
        "get_trends",
        {"days": 7, "org_wide": True},
        state,
    )
    assert "dashboard_id" not in args
    assert "org_wide" not in args


def test_pin_tool_args_for_new_topic_intent_tool():
    state = HardAgentState(
        dashboard_id=6208,
        dashboard_locked=True,
        source="dashboard_selection",
    )
    args = pin_tool_args_for_state(
        "get_topic_intent_distribution",
        {"dashboard_id": 9999, "days": 7},
        state,
    )
    assert args["dashboard_id"] == 6208


def test_dashboard_selection_payload_from_hard_state():
    state = HardAgentState(
        dashboard_id=4076,
        dashboard_name="Generali 2026",
        dashboard_locked=True,
        source="dashboard_selection",
    )
    payload = state.dashboard_selection_payload()
    assert payload == {"id": 4076, "name": "Generali 2026"}


def test_new_dashboard_tools_registered_for_scope_pinning():
    missing = _NEW_DASHBOARD_TOOLS - _DASHBOARD_ARG_TOOLS
    assert not missing, f"Missing from _DASHBOARD_ARG_TOOLS: {missing}"
