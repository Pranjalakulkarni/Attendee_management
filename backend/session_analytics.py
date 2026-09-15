"""
session_analytics.py
"Generate session analytics" - Milestone 2.

Mirrors insights.py's two-tier design:
  - rule_based: fast, deterministic, always available.
  - llm: if ANTHROPIC_API_KEY is set, hands the computed stats to Claude
    for a short narrative. Falls back to rule_based automatically.
"""

import os
import json
from collections import Counter
from datetime import datetime, timezone
import requests

import venue_agent
import speaker_agent

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _pct(part, whole):
    return round((part / whole) * 100, 1) if whole else 0.0


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def compute_session_stats(conn) -> dict:
    sessions = conn.execute("SELECT * FROM sessions WHERE status != 'cancelled'").fetchall()
    venues = conn.execute("SELECT * FROM venues").fetchall()
    speakers = conn.execute("SELECT * FROM speakers").fetchall()

    total_sessions = len(sessions)
    by_track = Counter((s["track"] or "General") for s in sessions)

    by_day = Counter()
    by_hour = Counter()
    unassigned_venue = 0
    unassigned_speaker = 0
    fill_rates = []

    for s in sessions:
        try:
            start = _parse(s["start_time"])
            by_day[start.date().isoformat()] += 1
            by_hour[f"{start.hour:02d}"] += 1
        except Exception:
            pass
        if not s["venue_id"]:
            unassigned_venue += 1
        if not s["speaker_id"]:
            unassigned_speaker += 1
        if s["venue_id"]:
            v = conn.execute("SELECT capacity FROM venues WHERE id = ?", (s["venue_id"],)).fetchone()
            if v and v["capacity"]:
                fill_rates.append(min(1.0, (s["expected_attendance"] or 0) / v["capacity"]))

    venue_conflicts = venue_agent.detect_venue_conflicts(conn)
    speaker_conflicts = speaker_agent.detect_speaker_conflicts(conn)
    utilization = venue_agent.venue_utilization(conn)
    workload = speaker_agent.speaker_workload(conn)

    avg_utilization = round(sum(v["utilization_pct"] for v in utilization.values()) / len(utilization), 1) if utilization else 0.0
    avg_fill_rate = round(sum(fill_rates) / len(fill_rates) * 100, 1) if fill_rates else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sessions": total_sessions,
        "total_venues": len(venues),
        "total_speakers": len(speakers),
        "unassigned_venue_count": unassigned_venue,
        "unassigned_speaker_count": unassigned_speaker,
        "venue_conflict_count": len(venue_conflicts),
        "speaker_conflict_count": len(speaker_conflicts),
        "avg_venue_utilization_pct": avg_utilization,
        "avg_room_fill_rate_pct": avg_fill_rate,
        "sessions_by_track": dict(by_track),
        "sessions_by_day": dict(sorted(by_day.items())),
        "sessions_by_hour": dict(sorted(by_hour.items())),
        "venue_utilization": utilization,
        "speaker_workload": workload,
        "conflicts": {
            "venue": venue_conflicts,
            "speaker": speaker_conflicts,
        },
    }


def generate_rule_based_session_insights(stats: dict) -> list:
    insights = []
    total = stats["total_sessions"]
    if total == 0:
        return [{"type": "info", "text": "No sessions scheduled yet - insights will appear once sessions are created."}]

    if stats["venue_conflict_count"] > 0:
        insights.append({
            "type": "warning",
            "text": f"{stats['venue_conflict_count']} venue double-booking(s) detected - "
                    f"run the scheduling optimizer or reassign one of the conflicting sessions."
        })
    if stats["speaker_conflict_count"] > 0:
        insights.append({
            "type": "warning",
            "text": f"{stats['speaker_conflict_count']} speaker double-booking(s) detected - "
                    f"a speaker is assigned to overlapping sessions."
        })
    if stats["unassigned_venue_count"] > 0:
        insights.append({
            "type": "warning",
            "text": f"{stats['unassigned_venue_count']} session(s) have no venue assigned yet."
        })
    if stats["unassigned_speaker_count"] > 0:
        insights.append({
            "type": "warning",
            "text": f"{stats['unassigned_speaker_count']} session(s) have no speaker assigned yet."
        })

    util = stats["venue_utilization"]
    if util:
        underused = [name for name, v in util.items() if v["status"] == "available" and v["utilization_pct"] < 20 and v["sessions_hosted"] == 0]
        if underused:
            insights.append({
                "type": "info",
                "text": f"{', '.join(underused[:3])} {'is' if len(underused) == 1 else 'are'} sitting completely unused - "
                        f"consider consolidating sessions there or freeing the space up."
            })
        overused = [name for name, v in util.items() if v["utilization_pct"] > 80]
        if overused:
            insights.append({
                "type": "info",
                "text": f"{', '.join(overused[:3])} {'is' if len(overused) == 1 else 'are'} booked at over 80% capacity - "
                        f"a high-demand space worth protecting from last-minute changes."
            })

    if stats["avg_room_fill_rate_pct"] and stats["avg_room_fill_rate_pct"] < 40:
        insights.append({
            "type": "info",
            "text": f"Average expected room fill rate is only {stats['avg_room_fill_rate_pct']}% - "
                    f"several sessions may be booked into rooms larger than they need."
        })

    workload = stats["speaker_workload"]
    if workload:
        busiest = max(workload.items(), key=lambda kv: kv[1]["sessions"])
        if busiest[1]["sessions"] >= 3:
            insights.append({
                "type": "info",
                "text": f"{busiest[0]} is carrying the heaviest load with {busiest[1]['sessions']} sessions "
                        f"({busiest[1]['total_minutes']} minutes total) - check they have adequate breaks."
            })

    tracks = stats["sessions_by_track"]
    if tracks:
        top_track, top_count = max(tracks.items(), key=lambda kv: kv[1])
        share = _pct(top_count, total)
        if share > 50:
            insights.append({
                "type": "info",
                "text": f"'{top_track}' accounts for {share}% of all sessions - "
                        f"make sure other tracks aren't being under-resourced."
            })

    if not insights:
        insights.append({"type": "positive", "text": "Scheduling looks healthy - no conflicts, and venues/speakers are well utilized."})

    return insights


def generate_llm_session_insights(stats: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    rule_based = generate_rule_based_session_insights(stats)

    if not api_key:
        return {"mode": "rule_based", "insights": rule_based, "narrative": None}

    prompt = (
        "You are an event operations analyst specializing in venue and speaker "
        "scheduling. Given this JSON of session/venue/speaker statistics, write "
        "a short, punchy 3-4 sentence narrative summary for an event organizer "
        "highlighting the single most important scheduling issue or opportunity "
        "they should act on right now. Be concrete and reference actual numbers.\n\n"
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
