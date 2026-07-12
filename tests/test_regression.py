"""Tests for regression checklist formatting."""

from quality_loop.regression import format_regression_checklist


def test_format_regression_checklist_empty():
    assert "yok" in format_regression_checklist([])


def test_format_regression_checklist_numbered():
    text = format_regression_checklist(["Dashboard seç", "Pivot sorgusu"])
    assert "[REGRESSION]" in text
    assert "1." in text
    assert "Dashboard seç" in text
