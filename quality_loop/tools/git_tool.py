"""Git read/apply tools for the coding agent (deploy gated by env flags)."""

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from quality_loop.repo_scope import (
    get_write_repo_root,
    list_scoped_repos,
    resolve_read_path,
    resolve_write_path,
)


def _repo_root() -> Path:
    return get_write_repo_root()


def _git_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_ALLOW_GIT_PUSH", "").lower() in ("1", "true", "yes")


def _deploy_allowed() -> bool:
    return os.environ.get("QUALITY_LOOP_AUTO_DEPLOY", "").lower() in ("1", "true", "yes")


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    name = os.environ.get("QUALITY_LOOP_GIT_USER_NAME", "quality-loop").strip() or "quality-loop"
    email = os.environ.get("QUALITY_LOOP_GIT_USER_EMAIL", "quality-loop@pivony.local").strip()
    env.setdefault("GIT_AUTHOR_NAME", name)
    env.setdefault("GIT_AUTHOR_EMAIL", email)
    env.setdefault("GIT_COMMITTER_NAME", name)
    env.setdefault("GIT_COMMITTER_EMAIL", email)
    return env


class ApplyFixInput(BaseModel):
    file_path: str = Field(
        description="Path under write repo, e.g. src/core/agent_state.py or pivony-advisor/src/..."
    )
    new_content: str = Field(description="Full new file content")
    commit_message: str = Field(description="Short commit message (quality-loop prefix added)")


class ApplyAndDeployTool(BaseTool):
    name: str = "apply_fix_and_deploy"
    description: str = (
        "Write a file in the configured write repo, optionally git add/commit/push and restart advisor. "
        "Requires QUALITY_LOOP_ALLOW_GIT_PUSH=true and QUALITY_LOOP_AUTO_DEPLOY=true. "
        "Read-only scoped repos cannot be written."
    )
    args_schema: Type[BaseModel] = ApplyFixInput

    def _run(self, file_path: str, new_content: str, commit_message: str) -> str:
        resolved = resolve_write_path(file_path)
        if resolved is None:
            return (
                f"Refusing to write outside write repo: {file_path}. "
                "Only the Mimari'de seçilen write repo'ya yazılabilir."
            )
        repo, rel = resolved
        from quality_loop.repo_scope import read_scope, repo_path

        repo_slug = None
        scope = read_scope()
        for slug in [scope.get("write_repo"), *(scope.get("extra_write_repos") or [])]:
            path = repo_path(slug or "")
            if path and path.resolve() == repo.resolve():
                repo_slug = slug
                break
        full_path = (repo / rel).resolve()
        if not str(full_path).startswith(str(repo.resolve())):
            return f"Refusing to write outside repo: {file_path}"

        full_path.parent.mkdir(parents=True, exist_ok=True)
        before = ""
        if full_path.exists():
            before = full_path.read_text(encoding="utf-8")
        full_path.write_text(new_content, encoding="utf-8")
        results = [f"✓ wrote {repo_slug or 'repo'}/{rel}"]

        job_id = os.environ.get("QUALITY_LOOP_JOB_ID", "").strip()
        if job_id:
            try:
                from quality_loop.fix_snapshots import annotate_fix_snapshot, record_fix_snapshot

                snap = record_fix_snapshot(job_id, rel, before, new_content, repo=repo_slug)
                if snap.get("diff"):
                    results.append(
                        f"Δ snapshot +{snap.get('lines_added', 0)}/-{snap.get('lines_removed', 0)}"
                    )
            except Exception as exc:
                results.append(f"⚠ snapshot failed: {exc}")

        if not _git_allowed():
            results.append(
                "⊘ git push skipped (set QUALITY_LOOP_ALLOW_GIT_PUSH=true to enable)"
            )
            if job_id:
                try:
                    from quality_loop.fix_snapshots import annotate_fix_snapshot

                    annotate_fix_snapshot(
                        job_id,
                        rel,
                        repo=repo_slug,
                        git_push_status="skipped",
                        commit_hash=None,
                        commit_message=None,
                    )
                except Exception:
                    pass
            return "\n".join(results)

        commit_msg = f"[quality-loop] {commit_message.strip()}"
        commit_hash: str | None = None
        git_push_status = "failed"
        cmds = [
            ["git", "-C", str(repo), "add", rel],
            ["git", "-C", str(repo), "commit", "-m", commit_msg],
            ["git", "-C", str(repo), "push"],
        ]
        for cmd in cmds:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=_git_env())
            if proc.returncode != 0:
                if job_id:
                    try:
                        from quality_loop.fix_snapshots import annotate_fix_snapshot

                        annotate_fix_snapshot(
                            job_id,
                            rel,
                            repo=repo_slug,
                            commit_hash=commit_hash,
                            commit_message=commit_msg if commit_hash else None,
                            git_push_status="failed",
                        )
                    except Exception:
                        pass
                return "\n".join(results) + f"\nGit error ({' '.join(cmd)}): {proc.stderr}"
            results.append(f"✓ {cmd[2]}")
            if cmd[2] == "commit":
                rev = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    env=_git_env(),
                )
                if rev.returncode == 0 and rev.stdout.strip():
                    commit_hash = rev.stdout.strip()
            if cmd[2] == "push":
                git_push_status = "success"

        if job_id:
            try:
                from quality_loop.fix_snapshots import annotate_fix_snapshot

                annotate_fix_snapshot(
                    job_id,
                    rel,
                    repo=repo_slug,
                    commit_hash=commit_hash,
                    commit_message=commit_msg,
                    git_push_status=git_push_status,
                )
            except Exception as exc:
                results.append(f"⚠ git metadata snapshot failed: {exc}")

        if commit_hash:
            results.append(f"✓ commit {commit_hash}")

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
    file_path: str = Field(description="Path: <repo-slug>/relative/path or prefixsiz write repo path")


class ReadFileTool(BaseTool):
    name: str = "read_project_file"
    description: str = (
        "Read a scoped repo file. Use <repo-slug>/path (örn. pivony-mcp/src/pivony_mcp/...) "
        "or prefixless path under the write repo. pivony-api-dev is out of scope."
        "or prefixsiz path for write repo. Mimari sayfasındaki repo seçimine göre."
    )
    args_schema: Type[BaseModel] = ReadFileInput

    def _run(self, file_path: str) -> str:
        resolved = resolve_read_path(file_path)
        if resolved is None:
            return f"Invalid path: {file_path}"
        repo, rel = resolved
        full_path = (repo / rel).resolve()
        if not str(full_path).startswith(str(repo.resolve())):
            return f"Refusing to read outside repo: {file_path}"
        try:
            return full_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"File not found: {full_path}"


class ListProjectFilesTool(BaseTool):
    name: str = "list_project_files"
    description: str = "List Python/config files for write repo + Mimari'de seçilen read-only repolar."

    def _list_repo(self, repo: Path, prefix: str = "") -> list[str]:
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
                label = f"{prefix}{rel}" if prefix else rel
                files.append(label)
        return files

    def _run(self) -> str:
        files: list[str] = []
        scoped = list_scoped_repos()
        if not scoped:
            files.extend(self._list_repo(_repo_root()))
        else:
            write_root = _repo_root().resolve()
            seen_roots: set[str] = set()
            for slug, root in scoped:
                key = str(root.resolve())
                if key in seen_roots:
                    continue
                seen_roots.add(key)
                is_write = root.resolve() == write_root
                prefix = "" if is_write else f"{slug}/"
                files.extend(self._list_repo(root, prefix=prefix))
        return "\n".join(sorted(set(files))[:160])
