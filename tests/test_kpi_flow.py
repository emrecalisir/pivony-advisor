"""Tests for KPI creation flow helpers."""

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


_analytics = _load_module("core.analytics_scope", "analytics_scope.py")
if "core" not in sys.modules:
    sys.modules["core"] = type(sys)("core")
sys.modules["core.analytics_scope"] = _analytics

_agent_state = _load_module("core.agent_state", "agent_state.py")
sys.modules["core.agent_state"] = _agent_state

_chip = _load_module("core.chip_capabilities", "chip_capabilities.py")
sys.modules["core.chip_capabilities"] = _chip

_kpi_flow = _load_module("core.kpi_flow", "kpi_flow.py")

normalize_label = _kpi_flow.normalize_label
match_dashboard_by_name = _kpi_flow.match_dashboard_by_name
match_kpi_team_by_name = _kpi_flow.match_kpi_team_by_name
build_kpi_metric_picker = _kpi_flow.build_kpi_metric_picker
conversation_in_kpi_creation = _kpi_flow.conversation_in_kpi_creation
should_suppress_dashboard_picker = _kpi_flow.should_suppress_dashboard_picker
HardAgentState = _agent_state.HardAgentState


DASHBOARDS = [
    {"id": 6208, "name": "SURVEY"},
    {"id": 100, "name": "ACS"},
]


def test_normalize_label_strips_punctuation():
    assert normalize_label("Power-User") == "poweruser"
    assert normalize_label("SURVEY") == "survey"


def test_match_dashboard_by_name_exact_and_partial():
    assert match_dashboard_by_name("survey", DASHBOARDS) == 6208
    assert match_dashboard_by_name("SURVEY", DASHBOARDS) == 6208
    assert match_dashboard_by_name("acs", DASHBOARDS) == 100


def test_match_kpi_team_by_name():
    teams = [{"team_id": "u1", "team_name": "Power-User"}]
    assert match_kpi_team_by_name("power-user", teams) == "u1"
    assert match_kpi_team_by_name("power user", teams) == "u1"


def test_build_kpi_metric_picker_dedupes():
    data = {
        "success": {
            "custom_metrics": ["Oda", "F&B"],
            "general_metrics": ["NPS"],
            "ai_topics": [{"topic_id": 1, "topic_name": "Oda"}],
        }
    }
    picker = build_kpi_metric_picker(data, 6208, "SURVEY")
    assert picker is not None
    labels = [m["label"] for m in picker["metrics"]]
    assert labels == ["Oda", "F&B", "NPS"]


def test_conversation_in_kpi_creation_on_global_executive_page():
    turns = [("user", "yeni kpi oluşturmam lazım")]
    ctx = {"page": "global_executive", "is_kpi_page": True}
    assert conversation_in_kpi_creation(turns, ctx) is True


def test_suppress_dashboard_picker_when_metric_list_called():
    hard = HardAgentState(dashboard_id=6208, dashboard_locked=True)
    assert should_suppress_dashboard_picker(
        kpi_creation=True,
        hard=hard,
        turns=[],
        page_context={},
        user_id=None,
        tools_called={"get_kpi_metric_list"},
    )
