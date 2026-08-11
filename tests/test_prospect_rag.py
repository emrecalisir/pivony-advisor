"""Tests for Sonic Prospect RAG helpers."""

from prospect.chunking import (
    faq_documents,
    property_detail_documents,
    split_into_sections,
    text_documents,
)
from prospect.point_ids import prospect_point_id
from prospect.qdrant_store import tenant_filter


def test_prospect_point_id_stable():
    a = prospect_point_id(
        org_id="org1",
        bot_id=5,
        source_type="faq",
        source_id="faq_0",
        chunk_index=0,
    )
    b = prospect_point_id(
        org_id="org1",
        bot_id=5,
        source_type="faq",
        source_id="faq_0",
        chunk_index=0,
    )
    assert a == b
    assert a != prospect_point_id(
        org_id="org2",
        bot_id=5,
        source_type="faq",
        source_id="faq_0",
        chunk_index=0,
    )


def test_tenant_filter_has_org_and_bot():
    filt = tenant_filter("org-abc", 7)
    assert len(filt.must) == 2


def test_faq_documents_skip_empty():
    docs = faq_documents(org_id="o1", bot_id=1, faq_items=[{"q": "", "a": "x"}, {"q": "Q", "a": "A"}])
    assert len(docs) == 1
    assert "Q: Q" in docs[0].page_content
    assert docs[0].metadata["source_type"] == "faq"


def test_text_documents_chunk_metadata():
    docs = text_documents(
        org_id="o1",
        bot_id=2,
        source_type="pdf",
        source_id="pdf_x",
        title="Brochure",
        text="word " * 400,
    )
    assert len(docs) >= 1
    assert docs[0].metadata["bot_id"] == "2"
    assert docs[0].metadata["source_type"] == "pdf"


def test_split_into_sections():
    text = (
        "Intro line\n\n"
        "1. Hotels\n"
        "Hotel body with details.\n\n"
        "2. Policies\n"
        "Cancellation within 72 hours.\n\n"
        "Appendix A — Codes\n"
        "RT-001 mapping."
    )
    sections = split_into_sections(text)
    titles = [title for title, _ in sections]
    assert "1. Hotels" in titles
    assert "2. Policies" in titles
    assert any("Appendix A" in title for title in titles)


def test_property_detail_documents_extracts_adults_only():
    text = (
        "2. Antalya Hotel Inventory\n"
        "ANT-205 Royal Palm Ultra Lara — Adults-only wing available (18+). "
        "Rooftop infinity pool."
    )
    docs, _ = property_detail_documents(
        org_id="o1",
        bot_id=5,
        source_type="pdf",
        source_id="pdf_doc",
        title="Brochure",
        text=text,
    )
    assert len(docs) == 1
    assert docs[0].metadata["property_code"] == "ANT-205"
    assert "Adults-only wing available (18+)" in docs[0].page_content


def test_text_documents_include_section_header():
    text = "1. Transfer\nShared shuttle AYT to Lara hotels costs 12 EUR."
    docs = text_documents(
        org_id="o1",
        bot_id=2,
        source_type="pdf",
        source_id="pdf_x",
        title="Brochure",
        text=text,
    )
    assert any("Section: 1. Transfer" in doc.page_content for doc in docs)
