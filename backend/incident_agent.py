"""
incident_agent.py
The "Incident Agent" - Milestone 3.

Responsibilities:
  - Manage the incident lifecycle (open -> in_progress -> resolved).
  - Detect incidents that have gone stale (open too long for their severity)
    and suggest escalation ("implement incident management workflows").
  - Generate a live feed of operational alerts ("generate operational alerts").

Pure logic over the `incidents` table - no network calls, mirrors the other
Milestone 2/3 agents' design.
"""

from datetime import datetime, timezone

SEVERITY_ORDER = ["low", "medium", "high", "critical"]

# How long an incident can sit open before the agent flags it as stale, per severity.
STALE_THRESHOLD_MINUTES = {
    "critical": 15,
    "high": 30,
    "medium": 60,
    "low": 120,
}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def open_minutes(incident_row, now: datetime = None) -> int:
    now_dt = now or datetime.now(timezone.utc)
    end = _parse(incident_row["resolved_at"]) if incident_row["resolved_at"] else now_dt
    start = _parse(incident_row["created_at"])
    return max(0, int((end - start).total_seconds() / 60))


def next_severity(current: str) -> str:
    idx = SEVERITY_ORDER.index(current) if current in SEVERITY_ORDER else 0
    return SEVERITY_ORDER[min(idx + 1, len(SEVERITY_ORDER) - 1)]


def detect_stale_incidents(conn, now: datetime = None):
    """Open/in-progress incidents that have exceeded their severity's time budget."""
    now_dt = now or datetime.now(timezone.utc)
    rows = conn.execute("SELECT * FROM incidents WHERE status != 'resolved'").fetchall()
    stale = []
    for r in rows:
        mins = open_minutes(r, now_dt)
        threshold = STALE_THRESHOLD_MINUTES.get(r["severity"], 60)
        if mins >= threshold:
            stale.append({
                "id": r["id"], "title": r["title"], "severity": r["severity"],
                "status": r["status"], "open_minutes": mins, "threshold_minutes": threshold,
                "suggested_severity": next_severity(r["severity"]),
            })
    return sorted(stale, key=lambda x: -x["open_minutes"])


def compute_incident_stats(conn) -> dict:
    rows = conn.execute("SELECT * FROM incidents").fetchall()
    total = len(rows)
    by_status = {"open": 0, "in_progress": 0, "resolved": 0}
    by_category = {}
    by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    resolution_minutes = []

    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
        if r["status"] == "resolved" and r["resolved_at"]:
            resolution_minutes.append(open_minutes(r))

    avg_resolution = round(sum(resolution_minutes) / len(resolution_minutes), 1) if resolution_minutes else 0.0
    stale = detect_stale_incidents(conn)

    return {
        "total_incidents": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_severity": by_severity,
        "avg_resolution_minutes": avg_resolution,
        "stale_count": len(stale),
        "stale_incidents": stale,
    }


def generate_operational_alerts(conn) -> list:
    """
    The Incident Agent's live alert feed - rule-based, always available.
    Ordered roughly by urgency: critical open incidents first, then stale
    ones, then category spikes, then a note on anything the agent already
    auto-escalated on its own.
    """
    alerts = []
    stats = compute_incident_stats(conn)

    open_critical = conn.execute(
        "SELECT * FROM incidents WHERE severity = 'critical' AND status != 'resolved'"
    ).fetchall()
    for r in open_critical:
        alerts.append({
            "level": "critical",
            "text": f"CRITICAL: '{r['title']}'" + (f" at {r['location']}" if r["location"] else "") +
                    f" is still {r['status'].replace('_', ' ')}.",
        })

    for s in stats["stale_incidents"]:
        if s["severity"] == "critical":
            continue  # already covered above
        alerts.append({
            "level": "warning",
            "text": f"'{s['title']}' has been open for {s['open_minutes']} min (budget: {s['threshold_minutes']} min) - "
                    f"the Incident Agent will auto-escalate it to {s['suggested_severity']} shortly if untouched.",
        })

    # Category spike: 3+ incidents of the same category still unresolved.
    unresolved = [r for r in conn.execute("SELECT * FROM incidents WHERE status != 'resolved'").fetchall()]
    cat_counts = {}
    for r in unresolved:
        cat_counts[r["category"]] = cat_counts.get(r["category"], 0) + 1
    for cat, count in cat_counts.items():
        if count >= 3:
            alerts.append({
                "level": "warning",
                "text": f"{count} unresolved {cat} incidents at once - possible systemic issue, worth a dedicated look.",
            })

    # Confirm anything the automated workflow already acted on, so a human sees what changed.
    auto_escalated_open = conn.execute(
        "SELECT * FROM incidents WHERE auto_escalated = 1 AND status != 'resolved'"
    ).fetchall()
    for r in auto_escalated_open:
        alerts.append({
            "level": "info",
            "text": f"Incident Agent auto-escalated '{r['title']}' to {r['severity']} after it exceeded its response budget - no action was taken by staff.",
        })

    if not alerts:
        alerts.append({"level": "info", "text": "No active alerts - all incidents are within their response-time budget."})

    return alerts


def auto_escalate_stale_incidents(conn, now: datetime = None) -> list:
    """
    The automated half of the incident management workflow (Objective 4 /
    Objective 9): incidents that have exceeded their severity's response-time
    budget get bumped a severity level and marked in_progress automatically -
    no human has to click anything. Runs on a background timer (see main.py).

    Escalation is capped at 'critical': once there's nothing higher to escalate
    to, the agent leaves final resolution to a person - it will never resolve
    or downgrade an incident on its own.
    """
    now_dt = now or datetime.now(timezone.utc)
    stale = detect_stale_incidents(conn, now_dt)
    escalated = []

    for s in stale:
        if s["severity"] == "critical":
            continue  # nothing higher to escalate to; a human must resolve it
        new_severity = next_severity(s["severity"])
        conn.execute(
            "UPDATE incidents SET severity = ?, status = 'in_progress', auto_escalated = 1, updated_at = ? WHERE id = ?",
            (new_severity, now_dt.isoformat(), s["id"]),
        )
        escalated.append({"id": s["id"], "title": s["title"], "from_severity": s["severity"], "to_severity": new_severity})

    return escalated


def generate_incident_recommendations(conn) -> list:
    """
    AI-based recommendations (Objective 6) distinct from the alert feed:
    concrete next actions for staff, not just "something is wrong" flags.
    """
    recs = []

    unassigned_open = conn.execute(
        "SELECT * FROM incidents WHERE assigned_to IS NULL AND status != 'resolved'"
    ).fetchall()
    for r in unassigned_open:
        recs.append({
            "priority": "high" if r["severity"] in ("critical", "high") else "medium",
            "action": f"Assign staff to '{r['title']}'",
            "reason": f"{r['severity'].capitalize()} severity {r['category']} incident with no one assigned yet.",
        })

    unresolved = conn.execute("SELECT * FROM incidents WHERE status != 'resolved'").fetchall()
    cat_counts = {}
    for r in unresolved:
        cat_counts[r["category"]] = cat_counts.get(r["category"], 0) + 1
    for cat, count in cat_counts.items():
        if count >= 3:
            recs.append({
                "priority": "medium",
                "action": f"Review {cat} incident handling process",
                "reason": f"{count} unresolved {cat} incidents at once suggests a root cause rather than isolated events.",
            })

    auto_escalated = conn.execute(
        "SELECT * FROM incidents WHERE auto_escalated = 1 AND status != 'resolved'"
    ).fetchall()
    for r in auto_escalated:
        recs.append({
            "priority": "high" if r["severity"] == "critical" else "medium",
            "action": f"Review and resolve '{r['title']}'",
            "reason": f"Auto-escalated to {r['severity']} by the Incident Agent - now requires human sign-off to close.",
        })

    # Sort by priority so the most urgent recommendation is always first.
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: order.get(r["priority"], 3))
