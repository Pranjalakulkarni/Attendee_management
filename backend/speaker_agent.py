"""
speaker_agent.py
The "Speaker Agent" - Milestone 2.

Responsibilities:
  - Manage speaker profiles, availability windows, and session assignments.
  - Match speakers to sessions by declared expertise/topic.
  - Prevent/detect a speaker being booked into two overlapping sessions.

Pure logic over `speakers` / `speaker_availability` / `sessions` - no
network calls, always available, mirrors venue_agent.py's design.
"""

from datetime import datetime


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return _parse(a_start) < _parse(b_end) and _parse(b_start) < _parse(a_end)


def _expertise_list(raw: str):
    return [e.strip() for e in (raw or "").split(",") if e.strip()]


def get_speaker_bookings(conn, speaker_id: int, exclude_session_id: int = None):
    query = "SELECT * FROM sessions WHERE speaker_id = ? AND status != 'cancelled'"
    params = [speaker_id]
    if exclude_session_id:
        query += " AND id != ?"
        params.append(exclude_session_id)
    return conn.execute(query, params).fetchall()


def is_speaker_booked_elsewhere(conn, speaker_id: int, start_time: str, end_time: str, exclude_session_id: int = None) -> bool:
    for booking in get_speaker_bookings(conn, speaker_id, exclude_session_id):
        if _overlaps(start_time, end_time, booking["start_time"], booking["end_time"]):
            return True
    return False


def is_within_availability(conn, speaker_id: int, start_time: str, end_time: str) -> bool:
    """If a speaker has declared no availability windows at all, treat them as generally available."""
    windows = conn.execute("SELECT * FROM speaker_availability WHERE speaker_id = ?", (speaker_id,)).fetchall()
    if not windows:
        return True
    s, e = _parse(start_time), _parse(end_time)
    for w in windows:
        if _parse(w["start_time"]) <= s and e <= _parse(w["end_time"]):
            return True
    return False


def is_speaker_available(conn, speaker_id: int, start_time: str, end_time: str, exclude_session_id: int = None) -> (bool, str):
    speaker = conn.execute("SELECT * FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
    if not speaker:
        return False, "Speaker not found."
    if speaker["status"] == "cancelled":
        return False, f"{speaker['name']} has cancelled their participation."
    if is_speaker_booked_elsewhere(conn, speaker_id, start_time, end_time, exclude_session_id):
        return False, f"{speaker['name']} is already booked for an overlapping session."
    if not is_within_availability(conn, speaker_id, start_time, end_time):
        return False, f"{speaker['name']} has not declared availability for this time slot."
    return True, "Available."


def find_available_speakers(conn, start_time: str, end_time: str, topic: str = None, exclude_session_id: int = None):
    """Returns confirmed speakers who are free for the slot, optionally filtered/ranked by topic match."""
    speakers = conn.execute("SELECT * FROM speakers WHERE status != 'cancelled'").fetchall()
    candidates = []
    for sp in speakers:
        ok, _ = is_speaker_available(conn, sp["id"], start_time, end_time, exclude_session_id)
        if not ok:
            continue
        candidates.append(sp)

    if topic:
        topic_lower = topic.strip().lower()

        def match_score(sp):
            tags = [t.lower() for t in _expertise_list(sp["expertise"])]
            exact = 1 if topic_lower in tags else 0
            partial = 1 if any(topic_lower in t or t in topic_lower for t in tags) else 0
            return (exact, partial, sp["rating"] or 0)

        candidates.sort(key=match_score, reverse=True)
    else:
        candidates.sort(key=lambda sp: sp["rating"] or 0, reverse=True)

    return candidates


def recommend_speaker(conn, start_time: str, end_time: str, topic: str = None, exclude_session_id: int = None):
    """Returns (speaker_row_or_None, reason_str) - the single best pick for a session."""
    candidates = find_available_speakers(conn, start_time, end_time, topic, exclude_session_id)
    if not candidates:
        if topic:
            return None, f"No speaker with expertise matching '{topic}' is available for this time slot."
        return None, "No speaker is available for this time slot."

    best = candidates[0]
    tags = _expertise_list(best["expertise"])
    if topic and topic.strip().lower() in [t.lower() for t in tags]:
        return best, f"{best['name']} is available and lists '{topic}' as an area of expertise."
    return best, f"{best['name']} is available (rating {best['rating']}/5)."


def detect_speaker_conflicts(conn):
    """Finds every pair of sessions assigned to the same speaker with overlapping times."""
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE speaker_id IS NOT NULL AND status != 'cancelled' ORDER BY speaker_id, start_time"
    ).fetchall()

    conflicts = []
    by_speaker = {}
    for s in sessions:
        by_speaker.setdefault(s["speaker_id"], []).append(s)

    for speaker_id, group in by_speaker.items():
        speaker = conn.execute("SELECT name FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
        speaker_name = speaker["name"] if speaker else f"Speaker #{speaker_id}"
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if _overlaps(a["start_time"], a["end_time"], b["start_time"], b["end_time"]):
                    conflicts.append({
                        "type": "speaker_double_booking",
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "session_a": {"id": a["id"], "title": a["title"], "start_time": a["start_time"], "end_time": a["end_time"]},
                        "session_b": {"id": b["id"], "title": b["title"], "start_time": b["start_time"], "end_time": b["end_time"]},
                        "message": f"{speaker_name} is booked for both '{a['title']}' and '{b['title']}' at overlapping times.",
                    })
    return conflicts


def speaker_workload(conn):
    """Sessions count + total speaking minutes per speaker - used by session analytics."""
    speakers = conn.execute("SELECT * FROM speakers").fetchall()
    result = {}
    for sp in speakers:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE speaker_id = ? AND status != 'cancelled'", (sp["id"],)
        ).fetchall()
        total_minutes = sum(
            max(0, (_parse(s["end_time"]) - _parse(s["start_time"])).total_seconds() / 60) for s in sessions
        )
        result[sp["name"]] = {
            "speaker_id": sp["id"],
            "sessions": len(sessions),
            "total_minutes": round(total_minutes),
            "rating": sp["rating"],
            "status": sp["status"],
        }
    return result


def auto_assign_session_speaker(conn, start_time: str, end_time: str, topic: str = None, exclude_session_id: int = None):
    """High-level entry point used by the scheduling workflow when a session has no speaker_id yet."""
    speaker, reason = recommend_speaker(conn, start_time, end_time, topic, exclude_session_id)
    return speaker, reason
