from core import morning_brief
from core.morning_brief import fetch_morning_brief_data, is_morning_brief


def test_is_morning_brief():
    assert is_morning_brief({"page": "morning_brief"})
    assert not is_morning_brief({"page": "global_executive"})
    assert not is_morning_brief(None)


def test_fetch_morning_brief_data_windows_topics_and_places(monkeypatch):
    calls = []

    def fake_fetch_metrics(user_id, dashboard_id, pivot_key, pivot_value, since, until):
        calls.append((pivot_value, since, until))
        if pivot_value:
            return {"review_count": 0 if since == until else 12, "sentiment": {}, "complaint_topics": []}
        return {
            "review_count": 100,
            "sentiment": {"negative_pct": 10, "positive_pct": 60},
            "topics": [{"topic": "F&B", "count": 40, "negative_pct": 28}],
        }

    monkeypatch.setattr(morning_brief, "fetch_metrics", fake_fetch_metrics)
    data = fetch_morning_brief_data("uid", 6208, "2026-09-23")

    assert (None, "2026-09-23", "2026-09-23") in calls
    assert (None, "2026-09-22", "2026-09-22") in calls
    assert (None, "2026-09-16", "2026-09-22") in calls
    assert data["totals"]["day"] == {"reviews": 100, "negative_pct": 10, "positive_pct": 60}
    assert data["topics"]["F&B"]["prior_day"] == {"reviews": 40, "negative_pct": 28}
    assert data["topics"]["Oda"]["day"] == {"reviews": None, "negative_pct": None}
    torba = data["places"][0]
    assert torba["vendor"] == "VOYAGE TORBA"
    assert torba["day"]["reviews"] == 0
    assert torba["baseline_7d"] == {"reviews": 12}
    assert torba["top_complaint_topic"] is None
