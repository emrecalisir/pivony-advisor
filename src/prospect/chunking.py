"""FAQ and free-text chunking for Sonic Prospect ingest."""

from __future__ import annotations

import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from prospect.config import CHUNK_OVERLAP, CHUNK_SIZE

# Numbered sections ("1. Company Overview") and appendices ("Appendix A — ...").
SECTION_PATTERN = re.compile(
    r"^(?:(\d+\.\s+.+)|(Appendix [A-Z][^\n]*))$",
    re.MULTILINE,
)

# Property detail paragraphs: "ANT-205 Royal Palm ... — Adults-only wing ..."
PROPERTY_DETAIL_PATTERN = re.compile(
    r"\b(ANT-\d{3})\b\s+(.+?)\s*[—–-]\s*(.+?)(?=\n\s*\bANT-\d{3}\b|\n\d+\.\s|\nAppendix|\Z)",
    re.DOTALL,
)

# Standalone property table/list rows.
PROPERTY_ROW_PATTERN = re.compile(
    r"^(ANT-\d{3})\s+(.+)$",
    re.MULTILINE,
)


def _prefix(org_id: str, bot_id: str | int, source_type: str, source_id: str) -> str:
    return f"[Org: {org_id}][Bot: {bot_id}][Source: {source_type}:{source_id}]\n"


def _make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split PDF/plain text into (section_title, section_body) pairs."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    matches = list(SECTION_PATTERN.finditer(cleaned))
    if not matches:
        return [("", cleaned)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = cleaned[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble))

    for index, match in enumerate(matches):
        title = (match.group(1) or match.group(2) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        body = cleaned[start:end].strip()
        if body or title:
            sections.append((title, body))
    return sections


def _document(
    *,
    org_id: str,
    bot_id: str | int,
    source_type: str,
    source_id: str,
    chunk_index: int,
    title: str,
    section: str,
    body: str,
    entity_type: str = "",
    property_code: str = "",
) -> Document:
    header = _prefix(org_id, bot_id, source_type, source_id)
    if title:
        header += f"Title: {title}\n"
    if section:
        header += f"Section: {section}\n"
    if property_code:
        header += f"Property: {property_code}\n"
    metadata: dict = {
        "org_id": org_id,
        "bot_id": str(bot_id),
        "source_type": source_type,
        "source_id": source_id,
        "chunk_index": chunk_index,
        "title": title,
    }
    if section:
        metadata["section"] = section
    if entity_type:
        metadata["entity_type"] = entity_type
    if property_code:
        metadata["property_code"] = property_code
    return Document(page_content=header + body.strip(), metadata=metadata)


def property_detail_documents(
    *,
    org_id: str,
    bot_id: str | int,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
    chunk_index_start: int = 0,
) -> tuple[list[Document], int]:
    """Dedicated chunks for property-specific paragraphs (e.g. ANT-205 adults-only)."""
    docs: list[Document] = []
    chunk_index = chunk_index_start
    seen_codes: set[str] = set()

    for match in PROPERTY_DETAIL_PATTERN.finditer(text or ""):
        code = match.group(1).strip().upper()
        name = " ".join(match.group(2).split())
        details = " ".join(match.group(3).split())
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        body = f"Property {code} — {name}\nDetails: {details}"
        docs.append(
            _document(
                org_id=org_id,
                bot_id=bot_id,
                source_type=source_type,
                source_id=f"{source_id}#{code}",
                chunk_index=0,
                title=title,
                section="Property details",
                body=body,
                entity_type="property_detail",
                property_code=code,
            )
        )
        chunk_index += 1

    for match in PROPERTY_ROW_PATTERN.finditer(text or ""):
        code = match.group(1).strip().upper()
        rest = " ".join(match.group(2).split())
        if code in seen_codes or len(rest) < 8:
            continue
        seen_codes.add(code)
        body = f"Property {code}\n{rest}"
        docs.append(
            _document(
                org_id=org_id,
                bot_id=bot_id,
                source_type=source_type,
                source_id=f"{source_id}#{code}",
                chunk_index=0,
                title=title,
                section="Property listing",
                body=body,
                entity_type="property_row",
                property_code=code,
            )
        )
        chunk_index += 1

    return docs, chunk_index


def faq_documents(
    *,
    org_id: str,
    bot_id: str | int,
    faq_items: list[dict],
) -> list[Document]:
    docs: list[Document] = []
    for index, item in enumerate(faq_items or []):
        q = (item.get("q") or "").strip()
        a = (item.get("a") or "").strip()
        if not q or not a:
            continue
        source_id = f"faq_{index}"
        body = f"Q: {q}\nA: {a}"
        docs.append(
            _document(
                org_id=org_id,
                bot_id=bot_id,
                source_type="faq",
                source_id=source_id,
                chunk_index=0,
                title="",
                section="FAQ",
                body=body,
            )
        )
    return docs


def text_documents(
    *,
    org_id: str,
    bot_id: str | int,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
) -> list[Document]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    docs: list[Document] = []

    property_docs, _ = property_detail_documents(
        org_id=org_id,
        bot_id=bot_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        text=cleaned,
    )
    docs.extend(property_docs)

    splitter = _make_splitter()
    chunk_index = 0
    for section_title, section_body in split_into_sections(cleaned):
        if not section_body.strip():
            continue
        for chunk in splitter.split_text(section_body):
            docs.append(
                _document(
                    org_id=org_id,
                    bot_id=bot_id,
                    source_type=source_type,
                    source_id=source_id,
                    chunk_index=chunk_index,
                    title=title,
                    section=section_title,
                    body=chunk,
                )
            )
            chunk_index += 1
    return docs
