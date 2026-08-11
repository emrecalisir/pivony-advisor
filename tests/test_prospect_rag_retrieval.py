"""Tests for Sonic Prospect query expansion."""

from prospect.rag import _expand_queries, _merge_search_results


def test_expand_queries_adults_only():
    queries = _expand_queries("Royal Palm Ultra Lara adults-only var mı?")
    assert len(queries) == 2
    assert "ANT-205" in queries[1]
    assert "adults-only" in queries[1].lower()


def test_merge_search_results_deduplicates_by_source():
    a = [{"source_id": "pdf_x", "chunk_index": 0, "score": 0.9, "snippet": "a"}]
    b = [{"source_id": "pdf_x", "chunk_index": 0, "score": 0.95, "snippet": "b"}]
    merged = _merge_search_results([a, b], limit=5)
    assert len(merged) == 1
    assert merged[0]["score"] == 0.9
