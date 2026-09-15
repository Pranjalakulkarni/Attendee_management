"""
venue_agent.py
The "Venue Agent" - Milestone 2.

Responsibilities:
  - Allocate venues to sessions automatically based on capacity + amenity
    requirements ("automate venue allocation based on event requirements").
  - Prevent/detect double-booked venues ("avoid scheduling conflicts").
  - Recommend the best-fit room among candidates to minimize wasted
    capacity ("optimize room utilization").

This module is pure logic over the `venues` / `sessions` tables - no
network calls - so it's fast, deterministic, and always available (mirrors
the rule_based half of insights.py's design).
"""

from datetime import datetime


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return _parse(a_start) < _parse(b_end) and _parse(b_start) < _parse(a_end)


def _amenities_list(raw: str):
    return [a.strip() for a in (raw or "").split(",") if a.strip()]


def _amenities_str(items):
    return ",".join(sorted(set(i.strip() for i in (items or []) if i.strip())))


def get_venue_bookings(conn, venue_id: int, exclude_session_id: int = None):
    query = "SELECT * FROM sessions WHERE venue_id = ? AND status != 'cancelled'"
    params = [venue_id]
    if exclude_session_id:
        query += " AND id != ?"
        params.append(exclude_session_id)
    return conn.execute(query, params).fetchall()


def is_venue_free(conn, venue_id: int, start_time: str, end_time: str, exclude_session_id: int = None) -> bool:
    for booking in get_venue_bookings(conn, venue_id, exclude_session_id):
        if _overlaps(start_time, end_time, booking["start_time"], booking["end_time"]):
            return False
    return True


def find_available_venues(conn, start_time: str, end_time: str, min_capacity: int = 0,
                           required_amenities=None, exclude_session_id: int = None):
    """Returns venues that are open, big enough, amenity-complete, and free for the slot."""
    required_amenities = set(a.strip().lower() for a in (required_amenities or []) if a.strip())
    venues = conn.execute("SELECT * FROM venues WHERE status = 'available'").fetchall()

    candidates = []
    for v in venues:
        if v["capacity"] < min_capacity:
            continue
        venue_amenities = set(a.lower() for a in _amenities_list(v["amenities"]))
        if not required_amenities.issubset(venue_amenities):
            continue
        if not is_venue_free(conn, v["id"], start_time, end_time, exclude_session_id):
            continue
        candidates.append(v)
    return candidates


def recommend_venue(conn, start_time: str, end_time: str, min_capacity: int = 0,
                     required_amenities=None, exclude_session_id: int = None):
    """
    Room-utilization optimization: among all valid candidates, pick the one
    with the LEAST excess capacity (so we don't waste a 500-seat hall on a
    20-person session), breaking ties by fewest amenities (again, don't
    reserve the most kitted-out room unless the session actually needs it).
    Returns (venue_row_or_None, reason_str).
    """
    candidates = find_available_venues(conn, start_time, end_time, min_capacity, required_amenities, exclude_session_id)
    if not candidates:
        return None, "No venue meets the capacity/amenity requirements and is free for this time slot."

    best = min(candidates, key=lambda v: (v["capacity"] - min_capacity, len(_amenities_list(v["amenities"]))))
    return best, f"Best fit: {best['capacity']} seats for a {min_capacity}-person session " \
                 f"({best['capacity'] - min_capacity} seats of headroom)."


def detect_venue_conflicts(conn):
    """Finds every pair of sessions sharing a venue with overlapping times."""
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE venue_id IS NOT NULL AND status != 'cancelled' ORDER BY venue_id, start_time"
    ).fetchall()

    conflicts = []
    by_venue = {}
    for s in sessions:
        by_venue.setdefault(s["venue_id"], []).append(s)

    for venue_id, group in by_venue.items():
        venue = conn.execute("SELECT name FROM venues WHERE id = ?", (venue_id,)).fetchone()
        venue_name = venue["name"] if venue else f"Venue #{venue_id}"
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if _overlaps(a["start_time"], a["end_time"], b["start_time"], b["end_time"]):
                    conflicts.append({
                        "type": "venue_double_booking",
                        "venue_id": venue_id,
                        "venue_name": venue_name,
                        "session_a": {"id": a["id"], "title": a["title"], "start_time": a["start_time"], "end_time": a["end_time"]},
                        "session_b": {"id": b["id"], "title": b["title"], "start_time": b["start_time"], "end_time": b["end_time"]},
                        "message": f"'{a['title']}' and '{b['title']}' are both booked in {venue_name} with overlapping times.",
                    })
    return conflicts


def venue_utilization(conn):
    """
    Per-venue utilization: booked hours vs. a standard 8-hour event day,
    number of sessions hosted, and average fill rate (expected_attendance / capacity).
    """
    venues = conn.execute("SELECT * FROM venues").fetchall()
    result = {}
    for v in venues:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE venue_id = ? AND status != 'cancelled'", (v["id"],)
        ).fetchall()
        booked_minutes = 0
        fill_rates = []
        days = set()
        for s in sessions:
            start, end = _parse(s["start_time"]), _parse(s["end_time"])
            booked_minutes += max(0, (end - start).total_seconds() / 60)
            days.add(start.date().isoformat())
            if v["capacity"]:
                fill_rates.append(min(1.0, (s["expected_attendance"] or 0) / v["capacity"]))

        # Assume an 8-hour operating day per distinct day the venue was used (at least 1 day for the denominator).
        available_minutes = max(1, len(days)) * 8 * 60
        result[v["name"]] = {
            "venue_id": v["id"],
            "capacity": v["capacity"],
            "sessions_hosted": len(sessions),
            "booked_hours": round(booked_minutes / 60, 1),
            "utilization_pct": round(min(100.0, (booked_minutes / available_minutes) * 100), 1),
            "avg_fill_rate_pct": round(sum(fill_rates) / len(fill_rates) * 100, 1) if fill_rates else 0.0,
            "status": v["status"],
        }
    return result


def auto_allocate_session_venue(conn, start_time: str, end_time: str, expected_attendance: int,
                                 required_amenities=None, exclude_session_id: int = None):
    """High-level entry point used by the scheduling workflow when a session has no venue_id yet."""
    venue, reason = recommend_venue(conn, start_time, end_time, expected_attendance, required_amenities, exclude_session_id)
    return venue, reason


def venue_live_status(conn, now: datetime = None):
    """
    Real-time venue availability ("track venue availability in real time"): for every venue,
    is it free right now, or occupied by a session - and until when? Kept timezone-naive to
    match the rest of the Milestone 2 scheduling data (see the note in seed_data.py).
    """
    now_dt = now or datetime.now()
    venues = conn.execute("SELECT * FROM venues ORDER BY name").fetchall()
    result = []

    for v in venues:
        if v["status"] != "available":
            result.append({
                "venue_id": v["id"], "name": v["name"], "capacity": v["capacity"],
                "live_status": v["status"],  # maintenance | closed
                "current_session": None, "free_at": None,
                "next_session": None,
            })
            continue

        sessions = conn.execute(
            "SELECT * FROM sessions WHERE venue_id = ? AND status != 'cancelled' ORDER BY start_time",
            (v["id"],),
        ).fetchall()

        current, upcoming = None, None
        for s in sessions:
            start, end = _parse(s["start_time"]), _parse(s["end_time"])
            if start <= now_dt < end:
                current = s
            elif start > now_dt and upcoming is None:
                upcoming = s

        if current:
            result.append({
                "venue_id": v["id"], "name": v["name"], "capacity": v["capacity"],
                "live_status": "occupied",
                "current_session": {"id": current["id"], "title": current["title"], "end_time": current["end_time"]},
                "free_at": current["end_time"],
                "next_session": None,
            })
        else:
            result.append({
                "venue_id": v["id"], "name": v["name"], "capacity": v["capacity"],
                "live_status": "free",
                "current_session": None,
                "free_at": None,
                "next_session": ({"id": upcoming["id"], "title": upcoming["title"], "start_time": upcoming["start_time"]}
                                  if upcoming else None),
            })

    return result
