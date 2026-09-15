"""
intelligence_engine.py
The "Event Intelligence Engine" - Milestone 4.

This is the capstone module: it doesn't replace any of the Milestone 1-3
agents, it orchestrates them. Per the brief:

  "It should: collect data from different event modules, process and
   analyze event data, identify patterns and trends, detect operational
   risks, monitor event KPIs, generate recommendations, support predictive
   analysis, provide real-time or near-real-time insights."

Design note on timestamps (read this before touching this file):
  - attendees.registered_at, checkins.checkin_time, and incidents.* are all
    timezone-AWARE (produced by database.now_iso()).
  - venues/speakers/sessions.* are all timezone-NAIVE (they mirror the
    browser's <input type="datetime-local"> values - see the note in
    seed_data.py). Comparing a naive and an aware datetime raises
    TypeError, which has broken this app twice before in earlier
    milestones. This file talks to BOTH families of data, so it keeps two
    separate "now" values throughout: `now_aware` for attendee/checkin/
    incident math, `now_naive` for venue/session math. Do not cross them.
"""

from datetime import datetime, timedelta, timezone

import venue_agent
import speaker_agent
import session_analytics
import sponsor_agent
import incident_agent
import ops_analytics


# --------------------------------------------------------------------------
# 1 & 2. Collect data from every module + agent orchestration
# --------------------------------------------------------------------------
def orchestrate_agents(conn) -> dict:
    """
    Runs every Milestone 1-3 agent's read-side logic together in one pass
    and returns their combined output. This is the "agent orchestration"
    layer everything else in this file builds on top of.
    """
    attendees = conn.execute("SELECT * FROM attendees").fetchall()
    checkins = conn.execute("SELECT * FROM checkins WHERE checkout_time IS NULL").fetchall()

    return {
        "attendees": {
            "total": len(attendees),
            "currently_checked_in": len(checkins),
        },
        "venues": {
            "utilization": venue_agent.venue_utilization(conn),
            "live_status": venue_agent.venue_live_status(conn),
            "conflicts": venue_agent.detect_venue_conflicts(conn),
        },
        "speakers": {
            "workload": speaker_agent.speaker_workload(conn),
            "conflicts": speaker_agent.detect_speaker_conflicts(conn),
        },
        "sessions": session_analytics.compute_session_stats(conn),
        "sponsors_and_incidents": ops_analytics.compute_ops_stats(conn),
    }


# --------------------------------------------------------------------------
# 3. Identify patterns and trends / 7. support predictive analysis
# --------------------------------------------------------------------------
def identify_trends(conn, now_aware: datetime = None) -> dict:
    """
    Simple, honest trend detection: compares the most recent 15-minute
    window against the 15 minutes before it for both registrations and
    check-ins, and does a naive linear projection forward. This is
    deliberately lightweight (no ML dependency) but genuinely responds to
    real data, matching the brief's "increasing rapidly" style signal.
    """
    now_aware = now_aware or datetime.now(timezone.utc)
    window = timedelta(minutes=15)
    recent_start = now_aware - window
    prior_start = now_aware - (window * 2)

    def _count_between(query, start, end):
        rows = conn.execute(query).fetchall()
        count = 0
        for r in rows:
            ts = r[0]
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if start <= dt < end:
                count += 1
        return count

    reg_recent = _count_between("SELECT registered_at FROM attendees", recent_start, now_aware)
    reg_prior = _count_between("SELECT registered_at FROM attendees", prior_start, recent_start)
    checkin_recent = _count_between("SELECT checkin_time FROM checkins", recent_start, now_aware)
    checkin_prior = _count_between("SELECT checkin_time FROM checkins", prior_start, recent_start)

    def _trend(recent, prior):
        if prior == 0 and recent == 0:
            return {"direction": "stable", "recent_15min": recent, "prior_15min": prior, "change_pct": 0.0, "projected_next_15min": recent}
        if prior == 0:
            return {"direction": "increasing rapidly", "recent_15min": recent, "prior_15min": prior, "change_pct": 100.0, "projected_next_15min": recent * 2}
        change_pct = round(((recent - prior) / prior) * 100, 1)
        if change_pct >= 30:
            direction = "increasing rapidly"
        elif change_pct >= 5:
            direction = "increasing"
        elif change_pct <= -30:
            direction = "dropping sharply"
        elif change_pct <= -5:
            direction = "decreasing"
        else:
            direction = "stable"
        projected = max(0, round(recent + (recent - prior)))
        return {"direction": direction, "recent_15min": recent, "prior_15min": prior, "change_pct": change_pct, "projected_next_15min": projected}

    return {
        "registration_trend": _trend(reg_recent, reg_prior),
        "checkin_trend": _trend(checkin_recent, checkin_prior),
    }


# --------------------------------------------------------------------------
# 4. Detect operational risks (the flagship "Hall A crowding" example)
# --------------------------------------------------------------------------
def detect_operational_risks(conn, lookahead_minutes: int = 20, now_naive: datetime = None,
                              now_aware: datetime = None) -> list:
    """
    Cross-references venue capacity, upcoming session timing, and live
    check-in velocity to produce exactly the kind of risk the brief's
    example describes:

        "High crowd density is expected at Hall A. Consider deploying
         additional check-in staff and opening an alternative entry point."

    Also covers a couple of other genuinely cross-module risk types
    (unassigned sessions starting soon, concurrent critical incidents)
    since "operational risk" isn't only about crowd density.
    """
    now_naive = now_naive or datetime.now()
    now_aware = now_aware or datetime.now(timezone.utc)
    risks = []

    trends = identify_trends(conn, now_aware)
    checkin_direction = trends["checkin_trend"]["direction"]
    reg_direction = trends["registration_trend"]["direction"]

    # --- Crowd density risk: venue capacity vs. an imminent session's expected attendance ---
    upcoming = conn.execute(
        "SELECT * FROM sessions WHERE status != 'cancelled' AND venue_id IS NOT NULL "
        "AND start_time > ? ORDER BY start_time", (now_naive.isoformat(),)
    ).fetchall()

    for s in upcoming:
        start = datetime.fromisoformat(s["start_time"])
        minutes_until = (start - now_naive).total_seconds() / 60
        if minutes_until > lookahead_minutes:
            break  # sessions are ordered by start_time, nothing closer left to check

        venue = conn.execute("SELECT * FROM venues WHERE id = ?", (s["venue_id"],)).fetchone()
        if not venue or not venue["capacity"]:
            continue

        fill_ratio = (s["expected_attendance"] or 0) / venue["capacity"]
        if fill_ratio < 0.85:
            continue

        message = (
            f"High crowd density is expected at {venue['name']} for '{s['title']}' "
            f"starting in {max(0, round(minutes_until))} minutes "
            f"({round(fill_ratio * 100)}% of {venue['capacity']}-seat capacity)."
        )
        if checkin_direction in ("increasing", "increasing rapidly"):
            message += f" Check-in queue is {checkin_direction} right now."
        message += " Consider deploying additional check-in staff and opening an alternative entry point."

        risks.append({
            "severity": "high" if fill_ratio >= 1.0 or checkin_direction == "increasing rapidly" else "medium",
            "category": "crowd_density",
            "message": message,
            "session_id": s["id"],
            "venue_id": venue["id"],
        })

    # --- Unassigned/conflicted session starting soon ---
    for s in upcoming:
        start = datetime.fromisoformat(s["start_time"])
        minutes_until = (start - now_naive).total_seconds() / 60
        if minutes_until > lookahead_minutes:
            break
        if s["status"] in ("conflict", "unassigned"):
            risks.append({
                "severity": "high",
                "category": "scheduling_gap",
                "message": f"'{s['title']}' starts in {max(0, round(minutes_until))} minutes but is still "
                           f"'{s['status']}' - run the scheduling optimizer or assign manually now.",
                "session_id": s["id"],
            })

    # --- Concurrent critical incidents ---
    open_critical = conn.execute(
        "SELECT COUNT(*) AS c FROM incidents WHERE severity = 'critical' AND status != 'resolved'"
    ).fetchone()["c"]
    if open_critical >= 2:
        risks.append({
            "severity": "critical",
            "category": "incident_load",
            "message": f"{open_critical} critical incidents are open at the same time - operations may be "
                       f"stretched thin. Consider pulling in additional staff.",
        })

    # --- Registration surge with no corresponding signal elsewhere (early warning, lower severity) ---
    if reg_direction == "increasing rapidly" and not any(r["category"] == "crowd_density" for r in risks):
        risks.append({
            "severity": "low",
            "category": "registration_surge",
            "message": "Registrations are increasing rapidly. Keep an eye on venue capacity for upcoming "
                       "sessions as attendance projections may shift.",
        })

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(risks, key=lambda r: severity_order.get(r["severity"], 9))


# --------------------------------------------------------------------------
# 5. Monitor event KPIs (feeds the Executive Dashboard)
# --------------------------------------------------------------------------
def compute_event_kpis(conn) -> dict:
    attendees_total = conn.execute("SELECT COUNT(*) AS c FROM attendees").fetchone()["c"]
    checked_in = conn.execute("SELECT COUNT(DISTINCT attendee_id) AS c FROM checkins WHERE checkout_time IS NULL").fetchone()["c"]
    checkin_rate = round((checked_in / attendees_total) * 100, 1) if attendees_total else 0.0

    util = venue_agent.venue_utilization(conn)
    avg_util = round(sum(v["utilization_pct"] for v in util.values()) / len(util), 1) if util else 0.0

    session_stats = session_analytics.compute_session_stats(conn)
    total_sessions = session_stats["total_sessions"]
    scheduled_ok = total_sessions - session_stats["unassigned_venue_count"] - session_stats["unassigned_speaker_count"] \
        - session_stats["venue_conflict_count"] - session_stats["speaker_conflict_count"]
    scheduling_health_pct = round(max(0, scheduled_ok) / total_sessions * 100, 1) if total_sessions else 100.0

    ops = ops_analytics.compute_ops_stats(conn)
    sponsors = ops["sponsors"]
    incidents = ops["incidents"]
    incident_health_pct = round(
        max(0, 100 - (incidents["by_status"].get("open", 0) + incidents["stale_count"]) * 10), 1
    )

    # A simple, transparent composite score - not a black box: equal-weighted average of the
    # four sub-health metrics above, each already expressed 0-100.
    health_score = round((checkin_rate * 0.25) + (scheduling_health_pct * 0.25) +
                          (sponsors["deliverable_completion_pct"] * 0.25) + (incident_health_pct * 0.25), 1)

    return {
        "attendees_total": attendees_total,
        "attendees_checked_in": checked_in,
        "checkin_rate_pct": checkin_rate,
        "avg_venue_utilization_pct": avg_util,
        "total_sessions": total_sessions,
        "scheduling_health_pct": scheduling_health_pct,
        "total_sponsors": sponsors["total_sponsors"],
        "total_contract_value": sponsors["total_contract_value"],
        "deliverable_completion_pct": sponsors["deliverable_completion_pct"],
        "open_incidents": incidents["by_status"].get("open", 0) + incidents["by_status"].get("in_progress", 0),
        "stale_incidents": incidents["stale_count"],
        "health_score": max(0.0, min(100.0, health_score)),
    }


# --------------------------------------------------------------------------
# 6. Generate recommendations (unifies + extends the per-agent recommenders)
# --------------------------------------------------------------------------
def generate_recommendations(conn, risks: list = None) -> list:
    risks = risks if risks is not None else detect_operational_risks(conn)
    recs = []

    for r in risks:
        recs.append({
            "priority": "high" if r["severity"] in ("critical", "high") else "medium",
            "category": r["category"],
            "action": r["message"],
        })

    ops = ops_analytics.compute_ops_stats(conn)
    for r in ops.get("recommendations", []):
        recs.append({"priority": r["priority"], "category": "sponsorship_or_incident",
                     "action": f"{r['action']} - {r['reason']}"})

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: order.get(r["priority"], 3))


# --------------------------------------------------------------------------
# 8. Real-time summary - the single call the Executive Dashboard uses
# --------------------------------------------------------------------------
def compute_intelligence_summary(conn) -> dict:
    now_naive = datetime.now()
    now_aware = datetime.now(timezone.utc)

    kpis = compute_event_kpis(conn)
    trends = identify_trends(conn, now_aware)
    risks = detect_operational_risks(conn, now_naive=now_naive, now_aware=now_aware)
    recommendations = generate_recommendations(conn, risks)
    orchestration = orchestrate_agents(conn)

    return {
        "generated_at": now_aware.isoformat(),
        "kpis": kpis,
        "trends": trends,
        "risks": risks,
        "recommendations": recommendations,
        "agents_orchestrated": ["venue_agent", "speaker_agent", "session_analytics",
                                 "sponsor_agent", "incident_agent", "ops_analytics"],
        "orchestration": orchestration,
    }


# --------------------------------------------------------------------------
# 9. Decision support - a ranked "what needs my attention right now" feed,
#    plus a one-paragraph plain-English executive summary. Both are derived
#    from real, live data (no placeholder text) so they change as the event
#    changes.
# --------------------------------------------------------------------------
def generate_decision_support(conn, kpis: dict = None, recommendations: list = None) -> dict:
    actions = []

    missing_speaker = conn.execute(
        "SELECT title, start_time FROM sessions WHERE speaker_id IS NULL AND status != 'cancelled' "
        "ORDER BY start_time LIMIT 5"
    ).fetchall()
    for s in missing_speaker:
        actions.append({
            "severity": "high",
            "category": "scheduling",
            "message": f"No speaker assigned to '{s['title']}' ({s['start_time']}).",
        })

    missing_venue = conn.execute(
        "SELECT title, start_time FROM sessions WHERE venue_id IS NULL AND status != 'cancelled' "
        "ORDER BY start_time LIMIT 5"
    ).fetchall()
    for s in missing_venue:
        actions.append({
            "severity": "high",
            "category": "scheduling",
            "message": f"No venue booked for '{s['title']}' ({s['start_time']}).",
        })

    _LEVEL_TO_SEVERITY = {"critical": "high", "warning": "medium", "info": "low"}
    for alert in incident_agent.generate_operational_alerts(conn)[:5]:
        actions.append({
            "severity": _LEVEL_TO_SEVERITY.get(alert.get("level"), "medium"),
            "category": "incident",
            "message": alert["text"],
        })

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    actions.sort(key=lambda a: order.get(a["severity"], 9))

    kpis = kpis if kpis is not None else compute_event_kpis(conn)
    score = kpis["health_score"]
    rating = "Needs attention" if score < 75 else "On track" if score < 90 else "Excellent"
    venue_capacity = conn.execute("SELECT COALESCE(SUM(capacity), 0) AS c FROM venues").fetchone()["c"]

    recommendations = recommendations if recommendations is not None else generate_recommendations(conn)
    top_recommendation = recommendations[0]["action"] if recommendations else \
        "No outstanding actions right now - the event is on track."

    executive_summary = (
        f"The event is currently rated {rating} with a health score of {score:.0f}/100. "
        f"{kpis['attendees_total']} attendee(s) are registered ({kpis['checkin_rate_pct']:.0f}% checked in) "
        f"across a venue capacity of {venue_capacity} seats. Top recommendation: {top_recommendation}"
    )

    return {"top_actions": actions[:8], "executive_summary": executive_summary}
