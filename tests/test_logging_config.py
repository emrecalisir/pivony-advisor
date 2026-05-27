"""Tests for dual-file logging setup."""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def _load_logging(tmp: Path):
    root = Path(__file__).resolve().parents[1]
    cfg_name = "_cfg_log_test"
    log_name = "_log_cfg_test"

    cfg_path = root / "src" / "core" / "config.py"
    cfg_spec = importlib.util.spec_from_file_location(cfg_name, cfg_path)
    cfg_mod = importlib.util.module_from_spec(cfg_spec)
    sys.modules[cfg_name] = cfg_mod
    cfg_spec.loader.exec_module(cfg_mod)
    cfg_mod.LOGS_DIR = str(tmp)
    cfg_mod.ADVISOR_LOG_PATH = str(tmp / "advisor.log")
    cfg_mod.HISTORY_LOG_PATH = str(tmp / "history.log")

    log_path = root / "src" / "core" / "logging_config.py"
    log_spec = importlib.util.spec_from_file_location(log_name, log_path)
    log_mod = importlib.util.module_from_spec(log_spec)
    sys.modules[log_name] = log_mod

    # Satisfy `from core.config import ...` inside logging_config
    sys.modules["core"] = type(sys)("core")
    sys.modules["core.config"] = cfg_mod

    log_spec.loader.exec_module(log_mod)
    log_mod._configured = False
    return log_mod, cfg_mod


def test_history_and_advisor_logs_are_separate():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_mod, cfg_mod = _load_logging(tmp)
        log_mod.setup_logging()

        advisor = log_mod.get_advisor_logger("test")
        advisor.info("startup ok")

        log_mod.log_conversation(
            user_id="uid-1",
            user_email="user@example.com",
            sector="hospitality",
            model="pivony-local-llm",
            messages=[{"role": "user", "content": "Merhaba"}],
            assistant_response="Selam",
            suggested_followups=["Devam?"],
        )

        history_text = Path(cfg_mod.HISTORY_LOG_PATH).read_text(encoding="utf-8")
        advisor_text = Path(cfg_mod.ADVISOR_LOG_PATH).read_text(encoding="utf-8")

        record = json.loads(history_text.strip().splitlines()[-1])
        assert record["user_id"] == "uid-1"
        assert record["user_email"] == "user@example.com"
        assert record["assistant_response"] == "Selam"
        assert "startup ok" in advisor_text
        assert "uid-1" not in advisor_text
