"""Git read/apply tools for the coding agent (deploy gated by env flags)."""

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _repo_root() -> Path:
    return Path(os.environ.get("PIVONY_REPO_ROOT", Path(__file__).resolve().parents[2]))


def _git_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_ALLOW_GIT_PUSH", "").lower() in ("1", "true", "yes")


def _deploy_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_AUTO_DEPLOY", "").lower() in ("1", "true", "yes")


class ApplyFixInput(BaseModel):
    file_path: str = Field(description="Path relative to repo root, e.g. src/core/agent_state.py")
    new_content: str = Field(description="Full new file content")
    commit_message: str = Field(description="Short commit message (quality-loop prefix added)")


class ApplyAndDeployTool(BaseTool):
    name: str = "apply_fix_and_deploy"
    description: str = (
        "Write a file, optionally git add/commit/push and restart advisor. "
        "Requires QUALITY_LOOP_ALLOW_GIT_PUSH=true and QUALITY_LOOP_AUTO_DEPLOY=true. "
        "Without those flags, only writes the file locally (dry-run safe)."
    )
    args_schema: Type[BaseModel] = ApplyFixInput

    def _run(self, file_path: str, new_content: str, commit_message: str) -> str:
        repo = _repo_root()
        full_path = (repo / file_path).resolve()
        if not str(full_path).startswith(str(repo.resolve())):
            return f"Refusing to write outside repo: {file_path}"

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_content, encoding="utf-8")
        results = [f"✓ wrote {file_path}"]

        if not _git_allowed():
            results.append(
                "⊘ git push skipped (set QUALITY_LOOP_ALLOW_GIT_PUSH=true to enable)"
            )
            return "\n".join(results)

        commit_msg = f"[quality-loop] {commit_message.strip()}"
        cmds = [
            ["git", "-C", str(repo), "add", file_path],
            ["git", "-C", str(repo), "commit", "-m", commit_msg],
            ["git", "-C", str(repo), "push"],
        ]
        for cmd in cmds:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return "\n".join(results) + f"\nGit error ({' '.join(cmd)}): {proc.stderr}"
            results.append(f"✓ {cmd[2]}")

        if not _deploy_allowed():
            results.append(
                "⊘ deploy skipped (set QUALITY_LOOP_AUTO_DEPLOY=true to enable)"
            )
            return "\n".join(results)

        deploy_cmd = os.environ.get(
            "DEPLOY_CMD",
            "systemctl restart pivony-advisor",
        )
        proc = subprocess.run(
            deploy_cmd.split(),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            results.append("✓ deploy completed")
        else:
            results.append(f"⚠ deploy warning: {proc.stderr[:300]}")

        return "\n".join(results)


class ReadFileInput(BaseModel):
    file_path: str = Field(description="Relative path under repo root")


class ReadFileTool(BaseTool):
    name: str = "read_project_file"
    description: str = "Read a project file from PIVONY_REPO_ROOT (default: pivony-advisor root)."
    args_schema: Type[BaseModel] = ReadFileInput

    def _run(self, file_path: str) -> str:
        full_path = _repo_root() / file_path
        try:
            return full_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"File not found: {full_path}"


class ListProjectFilesTool(BaseTool):
    name: str = "list_project_files"
    description: str = "List Python/config files in the repo (excludes venv, .git, quality_loop outputs)."

    def _run(self) -> str:
        repo = _repo_root()
        patterns = ["**/*.py", "**/*.txt", "**/*.yaml", "**/*.yml", "**/*.md"]
        ignore = {".git", "__pycache__", "node_modules", ".venv", "venv", "quality_loop/outputs"}
        files: list[str] = []
        for pattern in patterns:
            for path in glob.glob(str(repo / pattern), recursive=True):
                rel = os.path.relpath(path, repo)
                if any(part in ignore for part in Path(rel).parts):
                    continue
                if "quality_loop/outputs" in rel:
                    continue
                files.append(rel)
        return "\n".join(sorted(set(files))[:80])
