"""Persistent per-file checkpoint so ingest can resume after errors."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

_CHECKPOINT_VERSION = 2
_FILE_LINE_RE = re.compile(
    r"File \d+/\d+: (etsreviews_part_(\d+)\.md)",
)
_DONE_LINE_RE = re.compile(
    r"DONE (\d{4}-\d{2}) file \d+/\d+ (etsreviews_part_(\d+)\.md)",
)
_MONTH_STREAM_RE = re.compile(
    r"File-stream ingest: \d+ part file\(s\) under .*/(\d{4}-\d{2})\b",
)
_MONTH_HEADER_RE = re.compile(r"=== Month (\d{4}-\d{2}) ")
_MONTH_COMPLETE_RE = re.compile(r"=== Month (\d{4}-\d{2}) COMPLETE")


class IngestCheckpoint:
    """Tracks successfully indexed source files (blob paths)."""

    def __init__(self, path: str | Path, *, local_prefix: str = "hospitality") -> None:
        self.path = Path(path)
        self.local_prefix = local_prefix.strip("/")
        self.completed: set[str] = set()
        self.chunks_indexed: int = 0
        self.updated_at: str | None = None
        self.last_blob: str | None = None
        self.last_month: str | None = None

    def load(self) -> int:
        if not self.path.is_file():
            return 0
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("version") not in (1, _CHECKPOINT_VERSION):
            return 0
        self.completed = set(data.get("completed_files", []))
        self.chunks_indexed = int(data.get("chunks_indexed", 0))
        self.updated_at = data.get("updated_at")
        self.last_blob = data.get("last_blob")
        self.last_month = data.get("last_month")
        return len(self.completed)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": _CHECKPOINT_VERSION,
            "completed_files": sorted(self.completed),
            "chunks_indexed": self.chunks_indexed,
            "last_blob": self.last_blob,
            "last_month": self.last_month,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        tmp.replace(self.path)
        self.updated_at = payload["updated_at"]

    def clear(self) -> None:
        self.completed.clear()
        self.chunks_indexed = 0
        self.updated_at = None
        self.last_blob = None
        self.last_month = None
        if self.path.is_file():
            self.path.unlink()

    def is_empty(self) -> bool:
        return not self.completed

    def is_done(self, blob_name: str) -> bool:
        return blob_name in self.completed

    def mark_done(self, blob_name: str, chunks: int) -> None:
        self.completed.add(blob_name)
        self.chunks_indexed += chunks
        self.last_blob = blob_name
        parts = blob_name.split("/")
        self.last_month = parts[-2] if len(parts) >= 2 else None
        self.save()

    def count_in_month(self, month: str) -> int:
        prefix = f"{self.local_prefix}/{month}/" if self.local_prefix else f"{month}/"
        return sum(1 for blob in self.completed if blob.startswith(prefix))

    def resume_hint(self, month: str, total_files: int) -> str:
        done = self.count_in_month(month)
        remaining = max(0, total_files - done)
        return f"month={month} checkpoint={done}/{total_files} remaining={remaining}"

    def bootstrap_from_log(
        self,
        log_path: str | Path,
        *,
        local_dir: str | Path,
    ) -> int:
        """Best-effort: mark files already logged as indexed (avoids re-work after upgrade)."""
        log_file = Path(log_path)
        if not log_file.is_file():
            return 0

        text = log_file.read_text(encoding="utf-8", errors="replace")
        completed_months = set(_MONTH_COMPLETE_RE.findall(text))
        added = 0

        for month in sorted(completed_months):
            month_dir = Path(local_dir) / month
            if not month_dir.is_dir():
                continue
            for path in sorted(month_dir.glob("etsreviews_part_*.md")):
                blob = self._blob_name(month, path.name)
                if blob not in self.completed:
                    self.completed.add(blob)
                    added += 1

        current_month: str | None = None
        max_part_by_month: dict[str, int] = {}
        for line in text.splitlines():
            header = _MONTH_HEADER_RE.search(line)
            if header:
                current_month = header.group(1)
            stream = _MONTH_STREAM_RE.search(line)
            if stream:
                current_month = stream.group(1)
            if current_month and current_month in completed_months:
                continue
            done_match = _DONE_LINE_RE.search(line)
            if done_match:
                current_month = done_match.group(1)
                part_num = int(done_match.group(2))
                max_part_by_month[current_month] = max(
                    max_part_by_month.get(current_month, 0),
                    part_num,
                )
                continue
            match = _FILE_LINE_RE.search(line)
            if match and current_month:
                part_num = int(match.group(2))
                max_part_by_month[current_month] = max(
                    max_part_by_month.get(current_month, 0),
                    part_num,
                )

        for month, max_part in max_part_by_month.items():
            if month in completed_months:
                continue
            month_dir = Path(local_dir) / month
            if not month_dir.is_dir():
                continue
            for part_num in range(1, max_part + 1):
                filename = f"etsreviews_part_{part_num:03d}.md"
                path = month_dir / filename
                if not path.is_file():
                    continue
                blob = self._blob_name(month, filename)
                if blob not in self.completed:
                    self.completed.add(blob)
                    added += 1

        if added:
            self.save()
        return added

    def _blob_name(self, month: str, filename: str) -> str:
        if self.local_prefix:
            return f"{self.local_prefix}/{month}/{filename}"
        return f"{month}/{filename}"
