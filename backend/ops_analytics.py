"""
ops_analytics.py
Sponsorship & Incident analytics - Milestone 3.

Same two-tier design as session_analytics.py: a fast deterministic
rule_based tier that's always available, and an optional LLM narrative
layer on top when ANTHROPIC_API_KEY is set.
"""

import os
import json
from datetime import datetime, timezone
import requests

import sponsor_agent
import incident_agent

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def compute_ops_stats(conn) -> dict:
    sponsor_stats = sponsor_agent.compute_sponsor_stats(conn)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sponsors": sponsor_stats,
        "incidents": incident_agent.compute_incident_stats(conn),
        "alerts": incident_agent.generate_operational_alerts(conn),
        "recommendations": (
            sponsor_agent.generate_sponsor_recommendations(conn, sponsor_stats) +
            incident_agent.generate_incident_recommendations(conn)
        ),
    }


def generate_rule_based_ops_insights(stats: dict) -> list:
    insights = []
    insights.extend(sponsor_agent.generate_rule_based_sponsor_insights(stats["sponsors"]))

    inc = stats["incidents"]
    if inc["total_incidents"] == 0:
        insights.append({"type": "info", "text": "No incidents logged yet - the Incident Agent will start surfacing patterns once reports come in."})
    else:
        if inc["by_status"].get("open", 0) > 0:
            insights.append({"type": "warning", "text": f"{inc['by_status']['open']} incident(s) are still open and unassigned."})
        if inc["stale_count"] > 0:
            insights.append({"type": "warning", "text": f"{inc['stale_count']} incident(s) have exceeded their severity's response-time budget."})
        if inc["avg_resolution_minutes"] > 0:
            insights.append({"type": "info", "text": f"Average resolution time so far is {inc['avg_resolution_minutes']} minutes."})
        if inc["by_status"].get("open", 0) == 0 and inc["by_status"].get("in_progress", 0) == 0 and inc["total_incidents"] > 0:
            insights.append({"type": "positive", "text": "Every logged incident has been resolved - operations are currently clean."})

    return insights


def generate_llm_ops_insights(stats: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    rule_based = generate_rule_based_ops_insights(stats)

    if not api_key:
        return {"mode": "rule_based", "insights": rule_based, "narrative": None}

    prompt = (
        "You are an event operations analyst covering sponsorship performance and "
        "on-site incident management. Given this JSON of sponsor and incident "
        "statistics, write a short, punchy 3-4 sentence narrative summary for an "
        "event organizer highlighting the single most important thing they should "
        "act on right now. Be concrete and reference actual numbers.\n\n"
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
