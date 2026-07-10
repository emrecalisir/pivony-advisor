"""Python source validation for coding-agent file writes."""

from __future__ import annotations

import ast
from pathlib import Path

_PYTHON_SUFFIXES = {".py"}


def is_python_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in _PYTHON_SUFFIXES


def validate_python_source(source: str) -> tuple[bool, str | None]:
    """Return (ok, error_message). error_message is set when ok is False."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        lineno = exc.lineno if exc.lineno is not None else "?"
        msg = exc.msg or "invalid syntax"
        return False, f"line {lineno}: {msg}"
    return True, None
