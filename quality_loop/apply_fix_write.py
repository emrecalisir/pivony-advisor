"""Validate and write coding-agent file fixes with Python syntax gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quality_loop.python_syntax import is_python_path, validate_python_source


@dataclass(frozen=True)
class WriteFixResult:
    ok: bool
    message: str
    wrote: bool = False
    rolled_back: bool = False


def validate_and_write_file(full_path: Path, new_content: str, before: str = "") -> WriteFixResult:
    """Write new_content after syntax checks; rollback on roundtrip failure."""
    if is_python_path(full_path):
        ok, err = validate_python_source(new_content)
        if not ok:
            return WriteFixResult(
                ok=False,
                wrote=False,
                message=(
                    f"✗ syntax_error: refusing to write {full_path.name}: {err}\n"
                    "deploy_status: syntax_error — file not written"
                ),
            )

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(new_content, encoding="utf-8")

    if is_python_path(full_path):
        read_back = full_path.read_text(encoding="utf-8")
        ok, err = validate_python_source(read_back)
        if not ok:
            rolled_back = False
            if before:
                full_path.write_text(before, encoding="utf-8")
                rollback = "restored previous content"
                rolled_back = True
            elif full_path.exists():
                full_path.unlink()
                rollback = "removed new file"
                rolled_back = True
            else:
                rollback = "no rollback needed"
            return WriteFixResult(
                ok=False,
                wrote=False,
                rolled_back=rolled_back,
                message=(
                    f"✗ syntax_error: roundtrip validation failed for {full_path.name}: {err}; "
                    f"{rollback}\n"
                    "deploy_status: syntax_error — file not written"
                ),
            )

    return WriteFixResult(
        ok=True,
        wrote=True,
        message=f"✓ wrote {full_path.name} (file_written_and_valid)",
    )
