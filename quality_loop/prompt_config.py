"""Sector-specific prompt files for quality-loop agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PACKAGE_ROOT = Path(__file__).resolve().parent
_CONFIG_DIR = _PACKAGE_ROOT / "config"
_SECTORS_DIR = _CONFIG_DIR / "sectors"

PROMPT_AGENTS: dict[str, dict[str, str]] = {
    "qa": {
        "file": "qa_rubric.txt",
        "label": "QA Agent Rubric",
        "description": "QA Agent değerlendirme rubric'i — sektöre göre özelleştirilebilir.",
    },
    "cx_director": {
        "file": "cx_director_persona.txt",
        "label": "CX Director Persona",
        "description": "CX Director test persona'sı — hangi sektörden konuştuğunu belirler.",
    },
}

_SECTOR_LABELS: dict[str, str] = {
    "default": "Varsayılan (genel)",
    "hospitality": "Turizm / Otelcilik",
    "insurance": "Sigorta",
    "retail": "Perakende",
    "finance": "Finans",
}


def slugify_sector(sector: str) -> str:
    slug = re.sub(r"[^\w-]", "_", (sector or "").strip().lower())
    return slug or "default"


def _agent_file(agent_id: str) -> str:
    spec = PROMPT_AGENTS.get(agent_id)
    if not spec:
        raise KeyError(f"Unknown prompt agent: {agent_id}")
    return spec["file"]


def _default_path(agent_id: str) -> Path:
    return _CONFIG_DIR / _agent_file(agent_id)


def _sector_path(agent_id: str, sector: str) -> Path:
    slug = slugify_sector(sector)
    if slug == "default":
        return _default_path(agent_id)
    return _SECTORS_DIR / slug / _agent_file(agent_id)


def list_sectors() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {"id": "default", "label": _SECTOR_LABELS.get("default", "Varsayılan (genel)")}
    ]
    seen = {"default"}
    if _SECTORS_DIR.exists():
        for path in sorted(_SECTORS_DIR.iterdir()):
            if not path.is_dir():
                continue
            slug = path.name
            if slug in seen:
                continue
            seen.add(slug)
            rows.append(
                {
                    "id": slug,
                    "label": _SECTOR_LABELS.get(slug, slug.replace("_", " ").title()),
                }
            )
    return rows


def read_prompt(agent_id: str, sector: str = "default") -> dict[str, Any]:
    if agent_id not in PROMPT_AGENTS:
        raise KeyError(agent_id)
    slug = slugify_sector(sector)
    default_path = _default_path(agent_id)
    sector_path = _sector_path(agent_id, slug)
    if slug == "default":
        path = default_path
        is_override = False
    elif sector_path.exists():
        path = sector_path
        is_override = True
    else:
        path = default_path
        is_override = False
    content = path.read_text(encoding="utf-8")
    return {
        "agent_id": agent_id,
        "sector": slug,
        "content": content,
        "path": str(path.relative_to(_PACKAGE_ROOT)),
        "is_override": is_override,
        "uses_default": slug != "default" and not is_override,
        **PROMPT_AGENTS[agent_id],
    }


def write_prompt(agent_id: str, sector: str, content: str) -> dict[str, Any]:
    if agent_id not in PROMPT_AGENTS:
        raise KeyError(agent_id)
    slug = slugify_sector(sector)
    path = _sector_path(agent_id, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return read_prompt(agent_id, slug)


def list_prompts_meta() -> dict[str, Any]:
    return {
        "agents": [
            {"id": agent_id, **meta}
            for agent_id, meta in PROMPT_AGENTS.items()
        ],
        "sectors": list_sectors(),
        "storage": {
            "default": "quality_loop/config/<agent_file>",
            "sector_override": "quality_loop/config/sectors/<sector>/<agent_file>",
        },
    }
