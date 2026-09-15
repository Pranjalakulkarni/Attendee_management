"""
insights.py
Turns raw attendee/check-in rows into:
  1. structured analytics (demographics, behavior, sources)
  2. natural-language "AI insights" for organizers

Two insight modes:
  - rule_based: fast, deterministic, always available (no API key needed)
  - llm: if ANTHROPIC_API_KEY is set in the environment, the rule-based
    stats are handed to Claude to produce a richer narrative summary.
    Falls back to rule_based automatically if no key / call fails.
"""

import os
import json
from collections import Counter
from datetime import datetime, timezone
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _pct(part, whole):
    return round((part / whole) * 100, 1) if whole else 0.0


def compute_stats(conn) -> dict:
    attendees = conn.execute("SELECT * FROM attendees").fetchall()
    checkins = conn.execute("SELECT * FROM checkins").fetchall()

    total = len(attendees)
    total_checkins_ever = {c["attendee_id"] for c in checkins}
    total_checkins_count = len(total_checkins_ever)

    currently_checked_in_ids = {c["attendee_id"] for c in checkins if c["checkout_time"] is None}
    currently_checked_in_count = len(currently_checked_in_ids)
    genders = Counter((a["gender"] or "Unspecified").title() for a in attendees)
    countries = Counter((a["country"] or "Unknown") for a in attendees)
    cities = Counter((a["city"] or "Unknown") for a in attendees)
    tickets = Counter((a["ticket_type"] or "General") for a in attendees)
    sources = Counter((a["source"] or "web_form") for a in attendees)

    ages = [a["age"] for a in attendees if a["age"] is not None]
    age_buckets = Counter()
    for age in ages:
        if age < 18:
            bucket = "Under 18"
        elif age < 25:
            bucket = "18-24"
        elif age < 35:
            bucket = "25-34"
        elif age < 45:
            bucket = "35-44"
        elif age < 60:
            bucket = "45-59"
        else:
            bucket = "60+"
        age_buckets[bucket] += 1

    # check-in rate per ticket type (behavior signal)
    checkin_by_ticket = {}
    for ttype, count in tickets.items():
        checked = sum(
            1 for a in attendees
            if (a["ticket_type"] or "General") == ttype and a["id"] in total_checkins_ever
        )
        checkin_by_ticket[ttype] = {"registered": count, "checked_in": checked, "rate": _pct(checked, count)}

    # check-in rate per source (data-quality / channel-effectiveness signal)
    checkin_by_source = {}
    for src, count in sources.items():
        checked = sum(
            1 for a in attendees
            if (a["source"] or "web_form") == src and a["id"] in total_checkins_ever
        )
        checkin_by_source[src] = {"registered": count, "checked_in": checked, "rate": _pct(checked, count)}

    # registration timeline (by day)
    reg_by_day = Counter()
    for a in attendees:
        try:
            day = a["registered_at"][:10]
        except Exception:
            day = "unknown"
        reg_by_day[day] += 1

    # check-in timeline (by hour) - "real time" behavior curve
    checkin_by_hour = Counter()
    for c in checkins:
        try:
            hour = c["checkin_time"][11:13]
        except Exception:
            hour = "unknown"
        checkin_by_hour[hour] += 1

    # No-shows are people who have never checked in.
    no_shows = total - total_checkins_count 

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_registered": total,
        "total_checked_in": total_checkins_count,  # Historical total
        "currently_checked_in": currently_checked_in_count,
        "no_shows": no_shows,
        "historical_checkin_rate_pct": _pct(total_checkins_count, total),
        "current_checkin_rate_pct": _pct(currently_checked_in_count, total),
        "demographics": {
            "gender": dict(genders),
            "country": dict(countries.most_common(10)),
            "city": dict(cities.most_common(10)),
            "age_bucket": dict(age_buckets),
        },
        "ticket_types": dict(tickets),
        "sources": dict(sources),
        "behavior": {
            "checkin_by_ticket_type": checkin_by_ticket,
            "checkin_by_source": checkin_by_source,
            "registrations_by_day": dict(sorted(reg_by_day.items())),
            "checkins_by_hour": dict(sorted(checkin_by_hour.items())),
        },
    }


def generate_rule_based_insights(stats: dict) -> list:
    """Deterministic, template-driven insights. Always works, zero cost."""
    insights = []
    total = stats["total_registered"]
    if total == 0:
        return [{"type": "info", "text": "No registrations yet - insights will appear once attendees start signing up."}]

    # Check-in pace
    rate = stats["current_checkin_rate_pct"]
    if rate < 30:
        insights.append({
            "type": "warning",
            "text": f"Only {rate}% of registered attendees have checked in so far. "
                    f"Consider sending a reminder push notification or SMS to no-shows."
        })
    elif rate > 80:
        insights.append({
            "type": "positive",
            "text": f"Strong turnout - {rate}% of registered attendees have already checked in."
        })

    # Source effectiveness
    src_behavior = stats["behavior"]["checkin_by_source"]
    if src_behavior:
        best_src = max(src_behavior.items(), key=lambda kv: kv[1]["rate"])
        worst_src = min(src_behavior.items(), key=lambda kv: kv[1]["rate"])
        if best_src[0] != worst_src[0] and best_src[1]["registered"] >= 3:
            insights.append({
                "type": "info",
                "text": f"Attendees from '{best_src[0]}' show the highest check-in rate "
                        f"({best_src[1]['rate']}%), while '{worst_src[0]}' lags at {worst_src[1]['rate']}%. "
                        f"'{best_src[0]}' may be your most engaged acquisition channel."
            })

    # Ticket type behavior
    ticket_behavior = stats["behavior"]["checkin_by_ticket_type"]
    for ttype, data in ticket_behavior.items():
        if data["registered"] >= 5 and data["rate"] < 20:
            insights.append({
                "type": "warning",
                "text": f"'{ttype}' ticket holders have a low check-in rate ({data['rate']}%) "
                        f"despite {data['registered']} registrations - worth a targeted follow-up."
            })

    # Geographic concentration
    countries = stats["demographics"]["country"]
    if countries:
        top_country, top_count = max(countries.items(), key=lambda kv: kv[1])
        share = _pct(top_count, total)
        if share > 50:
            insights.append({
                "type": "info",
                "text": f"{share}% of attendees are from {top_country} - "
                        f"consider localizing signage, food options, or timing around this majority."
            })

    # Age skew
    age_buckets = stats["demographics"]["age_bucket"]
    if age_buckets:
        top_bucket, top_bucket_count = max(age_buckets.items(), key=lambda kv: kv[1])
        share = _pct(top_bucket_count, sum(age_buckets.values()))
        if share > 40:
            insights.append({
                "type": "info",
                "text": f"The {top_bucket} age group makes up {share}% of attendees - "
                        f"tailor session topics, networking format, and marketing tone accordingly."
            })

    # Peak check-in hour (operational / real-time insight)
    hours = stats["behavior"]["checkins_by_hour"]
    if hours:
        peak_hour, peak_count = max(hours.items(), key=lambda kv: kv[1])
        insights.append({
            "type": "info",
            "text": f"Check-in traffic peaks around {peak_hour}:00 with {peak_count} check-ins - "
                    f"staff entrances accordingly to avoid queues."
        })

    if not insights:
        insights.append({"type": "info", "text": "Registrations look healthy with no major anomalies detected yet."})

    return insights


def generate_llm_insights(stats: dict) -> dict:
    """
    Sends the computed stats to Claude for a richer narrative summary.
    Requires ANTHROPIC_API_KEY in the environment. Falls back to the
    rule-based engine (with a note) if unavailable or the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    rule_based = generate_rule_based_insights(stats)

    if not api_key:
        return {"mode": "rule_based", "insights": rule_based, "narrative": None}

    prompt = (
        "You are an event operations analyst. Given this JSON of attendee "
        "registration and check-in statistics, write a short, punchy 3-4 "
        "sentence narrative summary for an event organizer highlighting the "
        "single most important thing they should act on right now. "
        "Be concrete and reference actual numbers.\n\n"
        f"STATS:\n{json.dumps(stats, indent=2)}"
    )

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        narrative = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        ).strip()
        return {"mode": "llm", "insights": rule_based, "narrative": narrative or None}
    except Exception as exc:
        return {"mode": "rule_based", "insights": rule_based, "narrative": None, "llm_error": str(exc)}
