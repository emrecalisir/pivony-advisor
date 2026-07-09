"""Optional mount of quality-loop UI under the advisor API (port 8011)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("advisor.api")


def mount_quality_loop_ui(app) -> None:
    """Mount quality_loop UI at /quality-loop when QUALITY_LOOP_UI_MOUNT=true."""
    flag = os.environ.get("QUALITY_LOOP_UI_MOUNT", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return

    root = Path(__file__).resolve().parents[2]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from quality_loop.ui.app import app as ql_app
    except Exception as exc:
        logger.warning("Quality loop UI mount skipped: %s", exc)
        return

    app.mount("/quality-loop", ql_app)
    logger.info("Quality loop UI mounted at /quality-loop (root=%s)", root)
