"""
sponsor_agent.py
The "Sponsorship Agent" - Milestone 3.

Responsibilities:
  - Manage sponsor profiles, tiers, and contracted deliverables.
  - Track sponsor performance (booth visits, leads, mentions, impressions).
  - Flag sponsors who are underperforming relative to their peers so the
    organizer can follow up before the event ends, not after.

Pure logic over `sponsors` / `sponsor_deliverables` / `sponsor_engagement` -
no network calls, mirrors venue_agent.py / speaker_agent.py's design.
"""

METRIC_TYPES = ["booth_visits", "leads", "social_mentions", "impressions"]
TIER_ORDER = {"Platinum": 0, "Gold": 1, "Silver": 2, "Bronze": 3}


def deliverable_counts(conn, sponsor_id: int):
    rows = conn.execute("SELECT status FROM sponsor_deliverables WHERE sponsor_id = ?", (sponsor_id,)).fetchall()
    total = len(rows)
    completed = sum(1 for r in rows if r["status"] == "completed")
    return total, completed


def engagement_totals(conn, sponsor_id: int):
    rows = conn.execute(
        "SELECT metric_type, SUM(value) AS total FROM sponsor_engagement WHERE sponsor_id = ? GROUP BY metric_type",
        (sponsor_id,),
    ).fetchall()
    totals = {m: 0 for m in METRIC_TYPES}
    for r in rows:
        totals[r["metric_type"]] = r["total"] or 0
    return totals


def compute_sponsor_stats(conn) -> dict:
    # NOTE: 'prospect' sponsors are intentionally excluded here - they haven't signed on yet,
    # so their contract_value/tier shouldn't count toward the real portfolio totals. They live
    # in the search/approach pipeline instead (see search_sponsors() below).
    sponsors = conn.execute("SELECT * FROM sponsors WHERE status NOT IN ('cancelled', 'prospect')").fetchall()

    tier_breakdown = {}
    total_contract_value = 0.0
    engagement_by_sponsor = {}
    engagement_overall = {m: 0 for m in METRIC_TYPES}
    deliverable_total_all, deliverable_done_all = 0, 0

    for s in sponsors:
        tier_breakdown[s["tier"]] = tier_breakdown.get(s["tier"], 0) + 1
        total_contract_value += s["contract_value"] or 0

        totals = engagement_totals(conn, s["id"])
        engagement_by_sponsor[s["name"]] = totals
        for m in METRIC_TYPES:
            engagement_overall[m] += totals[m]

        d_total, d_done = deliverable_counts(conn, s["id"])
        deliverable_total_all += d_total
        deliverable_done_all += d_done

    # Underperforming = confirmed sponsor with below-average total engagement (leads + booth visits).
    underperforming = []
    if sponsors:
        scores = {
            s["name"]: engagement_by_sponsor[s["name"]]["leads"] + engagement_by_sponsor[s["name"]]["booth_visits"]
            for s in sponsors
        }
        avg_score = sum(scores.values()) / len(scores) if scores else 0
        for s in sponsors:
            if s["status"] == "confirmed" and scores[s["name"]] < avg_score * 0.5:
                underperforming.append({
                    "sponsor_id": s["id"], "name": s["name"], "tier": s["tier"],
                    "score": scores[s["name"]], "average_score": round(avg_score, 1),
                })

    deliverable_completion_pct = round((deliverable_done_all / deliverable_total_all) * 100, 1) if deliverable_total_all else 0.0

    return {
        "total_sponsors": len(sponsors),
        "total_contract_value": round(total_contract_value, 2),
        "tier_breakdown": tier_breakdown,
        "engagement_overall": engagement_overall,
        "engagement_by_sponsor": engagement_by_sponsor,
        "deliverable_total": deliverable_total_all,
        "deliverable_completed": deliverable_done_all,
        "deliverable_completion_pct": deliverable_completion_pct,
        "underperforming_sponsors": sorted(underperforming, key=lambda x: TIER_ORDER.get(x["tier"], 9)),
    }


def generate_rule_based_sponsor_insights(stats: dict) -> list:
    insights = []
    if stats["total_sponsors"] == 0:
        return [{"type": "info", "text": "No sponsors added yet - insights will appear once sponsors are on board."}]

    if stats["deliverable_total"] > 0 and stats["deliverable_completion_pct"] < 50:
        insights.append({
            "type": "warning",
            "text": f"Only {stats['deliverable_completion_pct']}% of contracted sponsor deliverables are marked "
                    f"complete - follow up before the event to avoid last-minute scrambling."
        })

    for u in stats["underperforming_sponsors"][:3]:
        insights.append({
            "type": "warning",
            "text": f"{u['name']} ({u['tier']}) is tracking well below average engagement "
                    f"({u['score']} vs. an average of {u['average_score']}) - consider a check-in call."
        })

    top_tier_count = stats["tier_breakdown"].get("Platinum", 0) + stats["tier_breakdown"].get("Gold", 0)
    if top_tier_count > 0:
        insights.append({
            "type": "positive",
            "text": f"{top_tier_count} Platinum/Gold sponsor(s) on board, contributing to a total contract "
                    f"value of ${stats['total_contract_value']:,.0f}."
        })

    if not insights:
        insights.append({"type": "positive", "text": "Sponsor deliverables and engagement both look healthy - no action needed right now."})

    return insights


def generate_sponsor_recommendations(conn, stats: dict) -> list:
    """
    AI-based recommendations (Objective 6) distinct from the insight narrative:
    concrete next actions for the organizer, not just "here's a number" flags.
    """
    recs = []

    for u in stats["underperforming_sponsors"]:
        recs.append({
            "priority": "high" if u["tier"] in ("Platinum", "Gold") else "medium",
            "action": f"Schedule a check-in call with {u['name']}",
            "reason": f"{u['tier']} sponsor tracking at {u['score']} engagement vs. an average of {u['average_score']}.",
        })

    sponsors = conn.execute("SELECT * FROM sponsors WHERE status = 'confirmed'").fetchall()
    for s in sponsors:
        total, done = deliverable_counts(conn, s["id"])
        pending_or_stuck = total - done
        if total > 0 and done == 0:
            recs.append({
                "priority": "high" if s["tier"] in ("Platinum", "Gold") else "medium",
                "action": f"Follow up on deliverables for {s['name']}",
                "reason": f"{pending_or_stuck} deliverable(s) contracted with zero marked complete yet.",
            })

        totals = engagement_totals(conn, s["id"])
        if sum(totals.values()) == 0:
            recs.append({
                "priority": "medium",
                "action": f"Confirm on-site setup for {s['name']}",
                "reason": "No engagement (booth visits, leads, mentions, or impressions) logged at all yet.",
            })

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: order.get(r["priority"], 3))


# ==============================================================================
# Sponsor search & outreach ("search the sponsor according to our requirement
# and approach them")
# ==============================================================================

INDUSTRIES = [
    "Technology", "Finance", "Healthcare", "Education", "Retail",
    "Food & Beverage", "Automotive", "Manufacturing", "Media & Entertainment",
    "Nonprofit", "Other",
]


def search_sponsors(conn, industry: str = None, tier: str = None, status: str = None,
                     min_value: float = None, max_value: float = None, q: str = None):
    """
    The Sponsorship Agent's discovery search: find sponsors (existing prospects or
    already-engaged ones) matching event requirements, so the organizer can decide
    who to approach next. Returns best-fit-first (highest contract value first
    within matching results, since a bigger potential deal is usually the one
    worth reaching out to first).
    """
    query = "SELECT * FROM sponsors WHERE 1=1"
    params = []
    if industry:
        query += " AND industry = ?"
        params.append(industry)
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    if status:
        query += " AND status = ?"
        params.append(status)
    if min_value is not None:
        query += " AND contract_value >= ?"
        params.append(min_value)
    if max_value is not None:
        query += " AND contract_value <= ?"
        params.append(max_value)
    if q:
        query += " AND (name LIKE ? OR contact_name LIKE ? OR notes LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    query += " ORDER BY contract_value DESC, name"

    return conn.execute(query, params).fetchall()


def draft_outreach_message(sponsor_row, event_name: str = "our event") -> dict:
    """
    Generates a ready-to-send outreach email tailored to the sponsor's tier and
    industry - the "approach them" half of the search-and-approach workflow.
    Rule-based and always available (no API key required), same design
    philosophy as the rest of this app's agents.
    """
    name = sponsor_row["name"]
    tier = sponsor_row["tier"]
    industry = sponsor_row["industry"] or "your industry"
    contact = sponsor_row["contact_name"] or "there"

    tier_pitch = {
        "Platinum": "a headline partnership with top-tier branding across the entire event",
        "Gold": "a high-visibility partnership with prominent branding and a dedicated session slot",
        "Silver": "a strong partnership package with booth space and app/website placement",
        "Bronze": "a flexible, cost-effective partnership to get your brand in front of attendees",
    }.get(tier, "a partnership tailored to your goals")

    subject = f"Partnership opportunity with {name} for {event_name}"
    body = (
        f"Hi {contact},\n\n"
        f"I'm reaching out from {event_name} - given {name}'s presence in {industry}, "
        f"we think there's a great fit for {tier_pitch}.\n\n"
        f"We'd love to put together a {tier}-tier sponsorship package built around what matters "
        f"most to your team - whether that's brand visibility, lead generation, or direct access "
        f"to our attendees.\n\n"
        f"Would you be open to a short call this week to discuss what a partnership could look like?\n\n"
        f"Looking forward to hearing from you.\n\n"
        f"Best regards,\nThe Event Team"
    )
    return {"subject": subject, "body": body}


def mark_sponsor_approached(conn, sponsor_id: int, now_iso_str: str):
    """Moves a prospect into the active pipeline once outreach has actually been sent."""
    row = conn.execute("SELECT * FROM sponsors WHERE id = ?", (sponsor_id,)).fetchone()
    if not row:
        return None
    new_status = "pending" if row["status"] == "prospect" else row["status"]
    conn.execute(
        "UPDATE sponsors SET status = ?, approached_at = ? WHERE id = ?",
        (new_status, now_iso_str, sponsor_id),
    )
    return conn.execute("SELECT * FROM sponsors WHERE id = ?", (sponsor_id,)).fetchone()
