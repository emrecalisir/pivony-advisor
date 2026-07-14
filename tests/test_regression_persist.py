"""Regression verification must not append turns to the session store."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# advisor_tool imports crewai at module load
sys.modules.setdefault("crewai", MagicMock())
sys.modules.setdefault("crewai.tools", MagicMock())

from quality_loop.regression import run_regression_verification
from quality_loop.session_store import append_turn, create_session, load_session


def test_regression_verification_does_not_persist_turns():
    session = create_session(user_id="u1", sector="hospitality")
    session_id = session["session_id"]
    before_count = len(load_session(session_id).get("messages") or [])

    mock_payload = {
        "session_id": session_id,
        "content": "Regression yanıtı tamam.",
        "tool_actions": [],
    }

    class FakeTool:
        def _run(self, **kwargs):
            import json

            assert kwargs.get("persist_turn") is False
            return json.dumps(mock_payload, ensure_ascii=False)

    with patch("quality_loop.tools.advisor_tool.PivonyAdvisorTool", FakeTool):
        with patch("quality_loop.session_store.append_turn") as append_mock:
            out = run_regression_verification(
                session_id, scenarios=["Doğrula: test senaryosu"], max_scenarios=1
            )

    after = load_session(session_id)
    assert len(after.get("messages") or []) == before_count
    append_mock.assert_not_called()
    assert out["scenarios_tested"] == 1
    assert out["status"] == "pass"
