"""Morning Brief: fetch the day's numbers server-side, let the model only write."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

from core.pivony_platform import fetch_metrics
from core.prompts import MASTER_PROMPT, get_sector_prompt

MORNING_BRIEF_PAGE = "morning_brief"
BRIEF_TOPICS = ("F&B", "Oda", "Hizmet")
BRIEF_VENDORS = ("VOYAGE TORBA", "MAXX ROYAL BODRUM")
VENDOR_PIVOT_KEY = "vendorName"
BASELINE_DAYS = 7
# pivony-api hosts run a single uWSGI worker each; wider fan-out queues past the 60s timeout.
FETCH_CONCURRENCY = 2
UNAVAILABLE = {"status": "unavailable"}

MORNING_BRIEF_INSTRUCTIONS = """MORNING BRIEF MODE
The JSON below was fetched server-side for dashboard "{dashboard}" and is the only data you may use. `day` is one full calendar day; `prior_day` is the day before; `baseline_7d` is the {baseline_days} days before `day`. Do not ask for a dashboard or period, do not mention tools, APIs or timeouts, and never write a number that is not in the JSON. null means no data: write "—", never 0. {{"status": "unavailable"}} means the data could not be loaded: write "—" and never describe it as zero or no reviews. If `totals.day` is unavailable, reply with only one sentence saying yesterday's data could not be loaded and to try again in a few minutes.

Write the whole brief in the language the user's request specifies. Keep topic and hotel names exactly as they appear in the JSON (do not translate "F&B").

Daily review volume on this dashboard swings with survey batches (weekends are far lower), so a volume change alone is neither good nor bad. Judge direction on negative_pct, comparing `day` with `prior_day` and `baseline_7d`. A move of 2 points or less is noise: call it stable and never base an action on it. Intensity from the largest gap vs `baseline_7d`: calm ≤ 2 points, elevated 3–5, acute > 5.

Format (short, executive):
1. Roll-up: one sentence — reviews on `day`, and the direction of negative share.
2. Pulse: one line — direction (better / worse / mixed / quiet) and intensity (calm / elevated / acute).
3. Drivers: one line per topic in `topics` — reviews, then negative share on `day` vs `prior_day` vs `baseline_7d`. Skip a topic with no reviews on `day`.
4. Places: one line per vendor in `places` — reviews and negative share on `day`, and its top complaint topic if present. A vendor with 0 reviews on `day`: say so with its `baseline_7d` volume. If both are empty, one line total. With fewer than 20 reviews, report the numbers but draw no conclusion.
5. Next actions: 1–3 bullets, each tied to a specific number above (which topic or place to drill into, and why). If nothing moved beyond noise, one bullet on the topic with the highest negative share. No generic advice.

DATA:
{data}"""


def is_morning_brief(page_context: dict | None) -> bool:
    return isinstance(page_context, dict) and page_context.get("page") == MORNING_BRIEF_PAGE


def _loaded(metrics: dict | None) -> bool:
    return isinstance(metrics, dict) and not metrics.get("error")


def _slice(metrics: dict | None) -> dict[str, Any]:
    if not _loaded(metrics):
        return dict(UNAVAILABLE)
    sentiment = metrics.get("sentiment") or {}
    return {
        "reviews": metrics.get("review_count"),
        "negative_pct": sentiment.get("negative_pct"),
        "positive_pct": sentiment.get("positive_pct"),
    }


def _topic(metrics: dict | None, name: str) -> dict[str, Any]:
    if not _loaded(metrics):
        return dict(UNAVAILABLE)
    for row in metrics.get("topics") or []:
        if isinstance(row, dict) and row.get("topic") == name:
            return {"reviews": row.get("count"), "negative_pct": row.get("negative_pct")}
    return {"reviews": None, "negative_pct": None}


def fetch_morning_brief_data(user_id: str, dashboard_id: int, day: str) -> dict[str, Any]:
    d = date.fromisoformat(day)
    prior = (d - timedelta(days=1)).isoformat()
    base_since = (d - timedelta(days=BASELINE_DAYS)).isoformat()
    windows = {"day": (day, day), "prior_day": (prior, prior), "baseline_7d": (base_since, prior)}

    jobs: dict[tuple[str, str | None], tuple] = {}
    for label, (since, until) in windows.items():
        jobs[(label, None)] = (None, since, until)
    for vendor in BRIEF_VENDORS:
        for label in ("day", "baseline_7d"):
            since, until = windows[label]
            jobs[(label, vendor)] = (vendor, since, until)

    def _run(spec: tuple) -> dict | None:
        vendor, since, until = spec
        return fetch_metrics(
            user_id,
            dashboard_id=dashboard_id,
            pivot_key=VENDOR_PIVOT_KEY if vendor else None,
            pivot_value=vendor,
            since=since,
            until=until,
        )

    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        results = dict(zip(jobs, pool.map(_run, jobs.values())))
    for key, value in results.items():
        if not _loaded(value):
            results[key] = _run(jobs[key])

    places = []
    for vendor in BRIEF_VENDORS:
        today = results[("day", vendor)]
        complaints = today.get("complaint_topics") if _loaded(today) else None
        baseline = _slice(results[("baseline_7d", vendor)])
        places.append({
            "vendor": vendor,
            "day": _slice(today),
            "baseline_7d": {"reviews": baseline["reviews"]} if "reviews" in baseline else baseline,
            "top_complaint_topic": (complaints[0] if complaints else None),
        })

    return {
        "day": day,
        "prior_day": prior,
        "baseline_7d": f"{base_since} → {prior}",
        "totals": {label: _slice(results[(label, None)]) for label in windows},
        "topics": {
            name: {label: _topic(results[(label, None)], name) for label in windows}
            for name in BRIEF_TOPICS
        },
        "places": places,
    }


def build_morning_brief_system_prompt(
    sector_slug: str, dashboard_name: str, data: dict[str, Any]
) -> str:
    parts = [MASTER_PROMPT]
    sector_prompt = get_sector_prompt(sector_slug)
    if sector_prompt:
        parts.append(sector_prompt)
    parts.append(
        MORNING_BRIEF_INSTRUCTIONS.format(
            dashboard=dashboard_name,
            baseline_days=BASELINE_DAYS,
            data=json.dumps(data, ensure_ascii=False, indent=1),
        )
    )
    return "\n\n".join(parts)
