"""Build Welcome-compatible chart payloads from Advisor tool JSON results."""

from __future__ import annotations

import json
from typing import Any


def _parse_tool_result(result: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(result, dict):
        return result
    if not result or not str(result).strip():
        return None
    try:
        parsed = json.loads(str(result))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _line_chart(
    *,
    title: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
    source_tool: str,
) -> dict[str, Any]:
    return {
        "chart_type": "line",
        "title": title,
        "labels": labels,
        "datasets": datasets,
        "source_tool": source_tool,
    }


def _bar_chart(
    *,
    title: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
    chart_type: str = "bar",
    source_tool: str,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "chart_type": chart_type,
        "title": title,
        "labels": labels,
        "datasets": datasets,
        "source_tool": source_tool,
    }
    out.update(extra)
    return out


def _charts_from_trends(data: dict[str, Any]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    volume = data.get("volume_daily") or []
    if isinstance(volume, list) and volume:
        labels = [str(r.get("day") or "") for r in volume]
        values = [float(r.get("count") or 0) for r in volume]
        if any(values):
            charts.append(
                _line_chart(
                    title="Günlük yorum hacmi",
                    labels=labels,
                    datasets=[
                        {
                            "label": "Yorum sayısı",
                            "data": values,
                            "borderColor": "#6366f1",
                            "backgroundColor": "rgba(99,102,241,0.15)",
                            "fill": True,
                        }
                    ],
                    source_tool="get_trends",
                )
            )

    sentiment = data.get("sentiment_daily") or []
    if isinstance(sentiment, list) and sentiment:
        labels = [str(r.get("day") or "") for r in sentiment]
        pos = [float(r.get("positive") or 0) for r in sentiment]
        neg = [float(r.get("negative") or 0) for r in sentiment]
        if any(pos) or any(neg):
            neg_pct = []
            for p, n in zip(pos, neg):
                total = p + n
                neg_pct.append(round(100.0 * n / total, 1) if total > 0 else 0.0)
            if any(neg_pct):
                charts.append(
                    _line_chart(
                        title="Günlük negatif yorum oranı (%)",
                        labels=labels,
                        datasets=[
                            {
                                "label": "Negatif %",
                                "data": neg_pct,
                                "borderColor": "#F44336",
                                "backgroundColor": "rgba(244,67,54,0.15)",
                                "fill": True,
                            }
                        ],
                        source_tool="get_trends",
                    )
                )
            charts.append(
                _line_chart(
                    title="Günlük duygu (pozitif / negatif yorum)",
                    labels=labels,
                    datasets=[
                        {
                            "label": "Pozitif",
                            "data": pos,
                            "borderColor": "#4CAF50",
                            "backgroundColor": "rgba(76,175,80,0.12)",
                        },
                        {
                            "label": "Negatif",
                            "data": neg,
                            "borderColor": "#F44336",
                            "backgroundColor": "rgba(244,67,54,0.12)",
                        },
                    ],
                    source_tool="get_trends",
                )
            )

    ratings = data.get("ratings_daily") or []
    if isinstance(ratings, list) and ratings:
        labels = [str(r.get("day") or "") for r in ratings]
        values = [
            float(r.get("avg_rating"))
            for r in ratings
            if r.get("avg_rating") is not None
        ]
        if values and len(labels) == len(values):
            charts.append(
                _line_chart(
                    title="Günlük ortalama puan",
                    labels=labels,
                    datasets=[
                        {
                            "label": "Ort. puan",
                            "data": values,
                            "borderColor": "#0ea5e9",
                            "backgroundColor": "rgba(14,165,233,0.12)",
                        }
                    ],
                    source_tool="get_trends",
                )
            )
    return charts


def _charts_from_topic_sentiment(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("topic_sentiment") or data.get("topics") or []
    if not isinstance(rows, list) or not rows:
        return []
    ordered = sorted(
        rows,
        key=lambda r: (-int((r or {}).get("count") or 0), str((r or {}).get("topic_name") or "").lower()),
    )[:12]
    labels = [str(r.get("topic_name") or "?") for r in ordered]
    if not labels:
        return []
    return [
        _bar_chart(
            title="Konu bazında duygu dağılımı (%)",
            chart_type="stacked_bar",
            labels=labels,
            datasets=[
                {
                    "label": "Pozitif",
                    "data": [
                        float(r.get("positive_percentage") or r.get("positive_pct") or 0)
                        for r in ordered
                    ],
                    "backgroundColor": "#4CAF50",
                },
                {
                    "label": "Nötr",
                    "data": [
                        float(r.get("neutral_percentage") or r.get("neutral_pct") or 0)
                        for r in ordered
                    ],
                    "backgroundColor": "#FFC107",
                },
                {
                    "label": "Negatif",
                    "data": [
                        float(r.get("negative_percentage") or r.get("negative_pct") or 0)
                        for r in ordered
                    ],
                    "backgroundColor": "#F44336",
                },
            ],
            source_tool="get_topic_sentiment",
            topic_review_counts=[int(r.get("count") or 0) for r in ordered],
        )
    ]


def _charts_from_topic_participation(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("topic_participation") or []
    if not isinstance(rows, list) or not rows:
        return []
    ordered = sorted(
        rows,
        key=lambda r: (-int((r or {}).get("count") or 0), str((r or {}).get("topic_name") or "").lower()),
    )[:12]
    labels = [str(r.get("topic_name") or "?") for r in ordered]
    values = [int(r.get("count") or 0) for r in ordered]
    if not labels or not any(values):
        return []
    return [
        _bar_chart(
            title="Konu katılımı (yorum sayısı)",
            labels=labels,
            datasets=[
                {
                    "label": "Yorum",
                    "data": values,
                    "backgroundColor": "#6366f1",
                }
            ],
            source_tool="get_topic_participation",
        )
    ]


def _charts_from_topic_intent(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("topics") or []
    if not isinstance(rows, list) or not rows:
        return []
    ordered = sorted(
        rows,
        key=lambda r: (-int((r or {}).get("count") or 0), str((r or {}).get("topic_name") or "").lower()),
    )[:10]
    labels = [str(r.get("topic_name") or "?") for r in ordered]
    intent_keys: list[str] = []
    for r in ordered:
        pcts = r.get("intent_pcts") or {}
        if isinstance(pcts, dict):
            for k in pcts:
                if k not in intent_keys:
                    intent_keys.append(k)
    if not labels or not intent_keys:
        return []
    palette = ["#F44336", "#FF9800", "#4CAF50", "#2196F3", "#9C27B0", "#607D8B"]
    datasets = []
    for idx, key in enumerate(intent_keys[:6]):
        datasets.append(
            {
                "label": key,
                "data": [
                    float((r.get("intent_pcts") or {}).get(key) or 0) for r in ordered
                ],
                "backgroundColor": palette[idx % len(palette)],
            }
        )
    return [
        _bar_chart(
            title="Konu bazında niyet dağılımı (%)",
            chart_type="stacked_bar",
            labels=labels,
            datasets=datasets,
            source_tool="get_topic_intent_distribution",
        )
    ]


def _charts_from_distribution(data: dict[str, Any]) -> list[dict[str, Any]]:
    dist = data.get("distribution")
    if not isinstance(dist, dict):
        return []
    kind = (data.get("kind") or "").strip().lower()
    items = dist.get("items") or []
    if isinstance(items, list) and items:
        labels = [
            str(i.get("label") or i.get("rating") or i.get("intent") or "?") for i in items
        ]
        values = [
            float(i.get("percentage") or i.get("count") or 0) for i in items
        ]
        if labels and any(values):
            title = {
                "sentiment": "Duygu dağılımı",
                "intent": "Niyet dağılımı (yorum bazında)",
                "platform": "Kanal dağılımı",
                "rating": "Yıldız dağılımı",
                "fraud": "Fraud dağılımı",
            }.get(kind, "Dağılım")
            return [
                _bar_chart(
                    title=title,
                    chart_type="doughnut" if kind in ("sentiment", "rating", "fraud") else "bar",
                    labels=labels,
                    datasets=[
                        {
                            "label": title,
                            "data": values,
                            "backgroundColor": [
                                "#4CAF50",
                                "#FFC107",
                                "#F44336",
                                "#2196F3",
                                "#9C27B0",
                                "#FF5722",
                            ][: len(values)],
                        }
                    ],
                    source_tool="get_distribution",
                )
            ]
    return []


def _topic_daily_palette() -> list[str]:
    return ["#6366f1", "#0ea5e9", "#4CAF50", "#F44336", "#FF9800", "#9C27B0"]


def _charts_from_topic_daily_sentiment(data: dict[str, Any]) -> list[dict[str, Any]]:
    topics = data.get("topics") or []
    if not isinstance(topics, list) or not topics:
        return []
    charts: list[dict[str, Any]] = []
    palette = _topic_daily_palette()
    for idx, topic in enumerate(topics[:4]):
        if not isinstance(topic, dict):
            continue
        series = topic.get("sentiment_daily") or []
        if not isinstance(series, list) or not series:
            continue
        labels = [str(r.get("day") or "") for r in series]
        values = [float(r.get("positive_pct") or 0) for r in series]
        if not labels or not any(values):
            continue
        name = str(topic.get("topic_name") or "?")
        charts.append(
            _line_chart(
                title=f"{name} — pozitif duygu trendi (%)",
                labels=labels,
                datasets=[
                    {
                        "label": "Pozitif %",
                        "data": values,
                        "borderColor": palette[idx % len(palette)],
                        "backgroundColor": "rgba(99,102,241,0.12)",
                        "fill": True,
                    }
                ],
                source_tool="get_topic_sentiment_daily",
            )
        )
    return charts


def _charts_from_topic_daily_participation(data: dict[str, Any]) -> list[dict[str, Any]]:
    topics = data.get("topics") or []
    if not isinstance(topics, list) or not topics:
        return []
    charts: list[dict[str, Any]] = []
    palette = _topic_daily_palette()
    for idx, topic in enumerate(topics[:4]):
        if not isinstance(topic, dict):
            continue
        series = topic.get("volume_daily") or []
        if not isinstance(series, list) or not series:
            continue
        labels = [str(r.get("day") or "") for r in series]
        values = [float(r.get("count") or 0) for r in series]
        if not labels or not any(values):
            continue
        name = str(topic.get("topic_name") or "?")
        charts.append(
            _line_chart(
                title=f"{name} — günlük yorum hacmi",
                labels=labels,
                datasets=[
                    {
                        "label": "Yorum",
                        "data": values,
                        "borderColor": palette[idx % len(palette)],
                        "backgroundColor": "rgba(99,102,241,0.12)",
                        "fill": True,
                    }
                ],
                source_tool="get_topic_participation_daily",
            )
        )
    return charts


def _charts_from_topic_trends_view(data: dict[str, Any]) -> list[dict[str, Any]]:
    charts = _charts_from_topic_daily_participation(data)
    charts.extend(_charts_from_topic_daily_sentiment(data))
    for chart in charts:
        chart["source_tool"] = "get_topic_trends_view"
    return charts


def _charts_from_review_statistics(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("review_statistics")
    if not isinstance(payload, dict):
        return []
    if payload.get("chart_type") != "review_statistics":
        return []
    out = dict(payload)
    out["source_tool"] = "get_review_statistics"
    out["title"] = (payload.get("header") or {}).get("title") or "Review Statistics"
    return [out]


def _charts_from_topic_trends(data: dict[str, Any]) -> list[dict[str, Any]]:
    rising = data.get("rising") or []
    falling = data.get("falling") or []
    charts: list[dict[str, Any]] = []
    if isinstance(rising, list) and rising:
        top = rising[:8]
        charts.append(
            _bar_chart(
                title="Yükselen konular (yorum hacmi değişimi)",
                labels=[str(r.get("topic") or "?") for r in top],
                datasets=[
                    {
                        "label": "Değişim",
                        "data": [int(r.get("change") or 0) for r in top],
                        "backgroundColor": "#4CAF50",
                    }
                ],
                source_tool="get_topic_trends",
                horizontal=True,
            )
        )
    if isinstance(falling, list) and falling:
        top = falling[:8]
        charts.append(
            _bar_chart(
                title="Düşen konular (yorum hacmi değişimi)",
                labels=[str(r.get("topic") or "?") for r in top],
                datasets=[
                    {
                        "label": "Değişim",
                        "data": [int(r.get("change") or 0) for r in top],
                        "backgroundColor": "#F44336",
                    }
                ],
                source_tool="get_topic_trends",
                horizontal=True,
            )
        )
    return charts


_TOOL_CHART_BUILDERS = {
    "get_trends": _charts_from_trends,
    "get_topic_sentiment": _charts_from_topic_sentiment,
    "get_topic_participation": _charts_from_topic_participation,
    "get_topic_intent_distribution": _charts_from_topic_intent,
    "get_distribution": _charts_from_distribution,
    "get_topic_trends": _charts_from_topic_trends,
    "get_topic_sentiment_daily": _charts_from_topic_daily_sentiment,
    "get_topic_participation_daily": _charts_from_topic_daily_participation,
    "get_topic_trends_view": _charts_from_topic_trends_view,
    "get_review_statistics": _charts_from_review_statistics,
}


def charts_from_tool_result(tool_name: str, result: str | dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return 0..N chart specs derived deterministically from a tool JSON payload."""
    builder = _TOOL_CHART_BUILDERS.get(tool_name or "")
    if builder is None:
        return []
    data = _parse_tool_result(result)
    if not data:
        return []
    if "error" in data and len(data) <= 2:
        return []
    try:
        charts = builder(data)
    except (TypeError, ValueError, KeyError):
        return []
    return [c for c in charts if isinstance(c, dict) and (
        c.get("labels") or c.get("chart_type") == "review_statistics"
    )]


def merge_chart_lists(
    existing: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Dedupe by title+source_tool and cap total charts per turn."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in [*existing, *new_items]:
        if not isinstance(item, dict):
            continue
        key = f"{item.get('source_tool')}::{item.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out
