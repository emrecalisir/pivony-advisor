"""Discover repos under masterr root and scope coding-agent read/write targets."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_ADVISOR_ROOT = _PACKAGE_ROOT.parent
_SCOPE_PATH = _PACKAGE_ROOT / "config" / "repo_scope.json"

_IGNORE_DIRS = {
    ".cursor",
    ".deploy_tmp",
    ".ipynb_checkpoints",
    ".venv",
    ".vscode",
    "node_modules",
    "jupyter",
    "keys",
    "output",
    "resources",
    "root_cause",
    "utils",
    "api",
    "temp_dynamo_exports",
    "reviews_export_19dec2025",
    "etsreviews_export_19dec2025",
    "emre-test",
    "google-cloud-sdk",
    "Tr_models",
    "engine",
}

_LEGACY_API_PREFIX = "api/"

# Coding agent must never modify production API repos via quality loop.
_BLOCKED_WRITE_REPOS = frozenset({"pivony-api-dev", "pivony-api"})


def get_masterr_root() -> Path:
    raw = os.environ.get("QUALITY_LOOP_MASTERR_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_ADVISOR_ROOT.parent.resolve()


def _slug(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name.strip()) or "repo"


def _is_repo_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    name = path.name
    if name.startswith("."):
        return False
    if name in _IGNORE_DIRS:
        return False
    if (path / ".git").is_dir():
        return True
    return name.startswith("pivony-")


def discover_repos(masterr_root: Path | None = None) -> list[dict[str, Any]]:
    root = (masterr_root or get_masterr_root()).resolve()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not _is_repo_dir(child):
            continue
        rows.append(
            {
                "id": child.name,
                "label": child.name,
                "path": str(child.resolve()),
                "has_git": (child / ".git").is_dir(),
            }
        )
    return rows


def _default_scope() -> dict[str, Any]:
    repos = discover_repos()
    ids = {r["id"] for r in repos}
    write_repo = "pivony-advisor" if "pivony-advisor" in ids else (repos[0]["id"] if repos else "")
    read_repos: list[str] = []
    extra_write_repos: list[str] = []
    if "pivony-mcp" in ids:
        read_repos.append("pivony-mcp")
        extra_write_repos.append("pivony-mcp")
    return {
        "masterr_root": str(get_masterr_root()),
        "write_repo": write_repo,
        "read_repos": read_repos,
        "extra_write_repos": extra_write_repos,
        "blocked_write_repos": sorted(_BLOCKED_WRITE_REPOS),
    }


def read_scope() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if _SCOPE_PATH.exists():
        try:
            with open(_SCOPE_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    defaults = _default_scope()
    masterr_root = str(get_masterr_root())
    write_repo = (data.get("write_repo") or defaults["write_repo"] or "").strip()
    read_repos = data.get("read_repos")
    if not isinstance(read_repos, list):
        read_repos = defaults["read_repos"]
    read_repos = [str(r).strip() for r in read_repos if str(r).strip()]
    extra_write = data.get("extra_write_repos")
    if not isinstance(extra_write, list):
        extra_write = defaults.get("extra_write_repos", [])
    extra_write_repos = [str(r).strip() for r in extra_write if str(r).strip()]
    blocked = data.get("blocked_write_repos")
    if not isinstance(blocked, list):
        blocked = defaults.get("blocked_write_repos", sorted(_BLOCKED_WRITE_REPOS))
    blocked_write_repos = sorted(
        {str(r).strip() for r in blocked if str(r).strip()} | set(_BLOCKED_WRITE_REPOS)
    )
    repos = discover_repos(Path(masterr_root))
    valid_ids = {r["id"] for r in repos}
    if write_repo not in valid_ids and repos:
        write_repo = defaults["write_repo"] if defaults["write_repo"] in valid_ids else repos[0]["id"]
    if write_repo in blocked_write_repos:
        fallback = defaults["write_repo"]
        write_repo = fallback if fallback in valid_ids and fallback not in blocked_write_repos else write_repo
    read_repos = [r for r in read_repos if r in valid_ids and r != write_repo]
    extra_write_repos = [
        r for r in extra_write_repos if r in valid_ids and r != write_repo and r not in blocked_write_repos
    ]
    return {
        "masterr_root": masterr_root,
        "write_repo": write_repo,
        "read_repos": read_repos,
        "extra_write_repos": extra_write_repos,
        "blocked_write_repos": blocked_write_repos,
        "repos": repos,
        "config_path": str(_SCOPE_PATH.relative_to(_PACKAGE_ROOT)),
    }


def write_scope(write_repo: str, read_repos: list[str]) -> dict[str, Any]:
    scope = read_scope()
    valid_ids = {r["id"] for r in scope["repos"]}
    write_repo = write_repo.strip()
    if write_repo not in valid_ids:
        raise ValueError(f"Unknown write repo: {write_repo}")
    if write_repo in scope.get("blocked_write_repos") or write_repo in _BLOCKED_WRITE_REPOS:
        raise ValueError(f"Repo is blocked for coding-agent writes: {write_repo}")
    cleaned = [r.strip() for r in read_repos if r.strip() and r.strip() in valid_ids and r.strip() != write_repo]
    payload = {
        "write_repo": write_repo,
        "read_repos": cleaned,
        "extra_write_repos": scope.get("extra_write_repos") or [],
        "blocked_write_repos": scope.get("blocked_write_repos") or sorted(_BLOCKED_WRITE_REPOS),
    }
    _SCOPE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SCOPE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return read_scope()


def repo_path(slug: str) -> Path | None:
    slug = slug.strip().rstrip("/")
    if not slug:
        return None
    for row in read_scope()["repos"]:
        if row["id"] == slug:
            return Path(row["path"]).resolve()
    return None


def get_write_repo_root() -> Path:
    env_root = os.environ.get("PIVONY_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    scope = read_scope()
    path = repo_path(scope["write_repo"])
    if path:
        return path
    return _DEFAULT_ADVISOR_ROOT.resolve()


def _scoped_read_map() -> dict[str, Path]:
    scope = read_scope()
    mapping: dict[str, Path] = {}
    write_slug = scope["write_repo"]
    write_path = repo_path(write_slug)
    if write_path:
        mapping[write_slug] = write_path
        mapping[""] = write_path
    for slug in scope["read_repos"]:
        path = repo_path(slug)
        if path:
            mapping[slug] = path
    legacy_api = os.environ.get("QUALITY_LOOP_API_REPO", "").strip()
    if legacy_api and _LEGACY_API_PREFIX.rstrip("/") not in mapping:
        mapping[_LEGACY_API_PREFIX.rstrip("/")] = Path(legacy_api).expanduser().resolve()
    return mapping


def resolve_read_path(file_path: str) -> tuple[Path, str] | None:
    normalized = file_path.strip().lstrip("/")
    if not normalized:
        return None
    mapping = _scoped_read_map()
    write_root = get_write_repo_root()
    scope = read_scope()
    write_slug = scope["write_repo"]
    known_repo_ids = {r["id"] for r in scope["repos"]}

    if "/" in normalized:
        prefix, rest = normalized.split("/", 1)
        if prefix in mapping:
            root = mapping[prefix]
            return root, rest
        if prefix in known_repo_ids or prefix in _BLOCKED_WRITE_REPOS:
            return None

    if normalized.startswith(_LEGACY_API_PREFIX):
        api_root = mapping.get(_LEGACY_API_PREFIX.rstrip("/"))
        if api_root:
            return api_root, normalized[len(_LEGACY_API_PREFIX) :]

    if write_slug and normalized.startswith(f"{write_slug}/"):
        return write_root, normalized[len(write_slug) + 1 :]

    return write_root, normalized


def resolve_write_path(file_path: str) -> tuple[Path, str] | None:
    resolved = resolve_read_path(file_path)
    if resolved is None:
        return None
    root, rel = resolved
    write_root = get_write_repo_root()
    if root.resolve() == write_root.resolve():
        return write_root, rel
    scope = read_scope()
    extra_slugs = set(scope.get("extra_write_repos") or [])
    for slug in extra_slugs:
        path = repo_path(slug)
        if path and root.resolve() == path.resolve():
            if slug in scope.get("blocked_write_repos", []) or slug in _BLOCKED_WRITE_REPOS:
                return None
            return path, rel
    return None


def list_scoped_repos() -> list[tuple[str, Path]]:
    scope = read_scope()
    rows: list[tuple[str, Path]] = []
    write_slug = scope["write_repo"]
    write_path = repo_path(write_slug)
    if write_path:
        rows.append((write_slug, write_path))
    for slug in scope["read_repos"]:
        path = repo_path(slug)
        if path:
            rows.append((slug, path))
    return rows


def apply_scope_to_env(env: dict[str, str] | None = None) -> dict[str, str]:
    out = dict(env or os.environ)
    scope = read_scope()
    write_path = repo_path(scope["write_repo"])
    if write_path:
        out["PIVONY_REPO_ROOT"] = str(write_path)
    read_paths = []
    for slug in scope["read_repos"]:
        path = repo_path(slug)
        if path:
            read_paths.append({"id": slug, "path": str(path)})
    out["QUALITY_LOOP_REPO_SCOPE"] = json.dumps(
        {
            "write_repo": scope["write_repo"],
            "read_repos": scope["read_repos"],
            "read_paths": read_paths,
        },
        ensure_ascii=False,
    )
    api_paths = [p for p in read_paths if p["id"] in ("pivony-api-dev", "pivony-api")]
    if api_paths:
        out["QUALITY_LOOP_API_REPO"] = api_paths[0]["path"]
    return out


def scope_summary() -> dict[str, Any]:
    scope = read_scope()
    write_path = repo_path(scope["write_repo"])
    read_rows = []
    for slug in scope["read_repos"]:
        path = repo_path(slug)
        if path:
            read_rows.append({"id": slug, "path": str(path)})
    return {
        **scope,
        "write_path": str(write_path) if write_path else "",
        "read_paths": read_rows,
        "prefix_help": (
            "read_project_file: <repo-slug>/path veya prefixsiz (write repo). "
            "Örn: pivony-mcp/src/pivony_mcp/server.py, src/core/agent.py. "
            "pivony-api-dev yazılamaz."
        ),
    }
