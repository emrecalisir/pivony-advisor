"""Lightweight tests (no langchain dependency)."""

from prospect.point_ids import prospect_point_id


def test_prospect_point_id_differs_by_bot():
    a = prospect_point_id(
        org_id="org1",
        bot_id=1,
        source_type="faq",
        source_id="faq_0",
        chunk_index=0,
    )
    b = prospect_point_id(
        org_id="org1",
        bot_id=2,
        source_type="faq",
        source_id="faq_0",
        chunk_index=0,
    )
    assert a != b
