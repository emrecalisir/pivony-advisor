"""Tests for Sonic Prospect RAG helpers."""

from prospect.chunking import faq_documents, text_documents
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
