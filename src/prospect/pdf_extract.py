"""Download and extract text from PDF URLs (Sonic Prospect knowledge docs)."""

from __future__ import annotations

import io
import logging

import requests

logger = logging.getLogger(__name__)


def extract_pdf_text(url: str, *, timeout_sec: int = 45) -> str:
    """Fetch PDF from URL and return extracted plain text."""
    response = requests.get(url, timeout=timeout_sec)
    response.raise_for_status()
    raw = response.content
    if not raw:
        return ""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for Sonic Prospect PDF ingest") from exc

    reader = PdfReader(io.BytesIO(raw))
    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("PDF page extract failed url=%s: %s", url, exc)
            text = ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)
