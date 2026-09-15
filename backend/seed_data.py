"""
seed_data.py
Populates the database with realistic-looking demo attendees and check-ins
so the dashboard has something to show immediately.

Run with:
    python seed_data.py [count]
"""

import random
import sys
from datetime import datetime, timedelta, timezone

from database import get_conn, init_db, now_iso

FIRST_NAMES = ["Aarav", "Isha", "Rohan", "Meera", "Kabir", "Ananya", "Vivaan", "Diya",
               "Arjun", "Sara", "Liam", "Emma", "Noah", "Olivia", "Mateo", "Sofia",
               "Yusuf", "Priya", "Chen", "Wei", "Fatima", "Omar", "Lucas", "Mia"]
LAST_NAMES = ["Sharma", "Patel", "Iyer", "Khan", "Gupta", "Verma", "Nair", "Reddy",
              "Smith", "Johnson", "Garcia", "Müller", "Rossi", "Tanaka", "Kim", "Silva"]
COMPANIES = ["Acme Corp", "Nimbus Labs", "Vertex Analytics", "Bright Path", "Orbit Systems",
             "Northwind Retail", "Cedar Health", "Quantum Foods", "Freelance", "Sunstone Media"]
JOB_TITLES = ["Software Engineer", "Product Manager", "Marketing Lead", "Data Analyst",
              "Founder", "Sales Executive", "HR Manager", "Designer", "Student", "Consultant"]
CITIES_COUNTRIES = [
    ("Nashik", "India"), ("Mumbai", "India"), ("Pune", "India"), ("Bengaluru", "India"),
    ("Delhi", "India"), ("New York", "USA"), ("San Francisco", "USA"), ("London", "UK"),
    ("Berlin", "Germany"), ("Singapore", "Singapore"), ("Dubai", "UAE"), ("Toronto", "Canada"),
]
TICKET_TYPES = ["General", "General", "General", "VIP", "Speaker", "Student"]
SOURCES = ["web_form", "web_form", "csv_import", "api_partner", "walk_in"]
GENDERS = ["Male", "Female", "Non-binary"]


def seed(count: int = 150):
    init_db()
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM attendees").fetchone()["c"]
        if existing:
            print(f"Database already has {existing} attendees - skipping seed. "
                  f"Delete data/attendees.db to reseed.")
            return

        base_time = datetime.now(timezone.utc) - timedelta(days=14)
        used_emails = set()

        for i in range(count):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            email = f"{first.lower()}.{last.lower()}{i}@example.com"
            if email in used_emails:
                continue
            used_emails.add(email)

            city, country = random.choice(CITIES_COUNTRIES)
            reg_time = base_time + timedelta(
                days=random.randint(0, 13), hours=random.randint(0, 23), minutes=random.randint(0, 59)
            )
            ticket = random.choice(TICKET_TYPES)
            source = random.choices(SOURCES, weights=[45, 20, 15, 12, 8])[0]

            cur = conn.execute(
                """INSERT INTO attendees
                   (name, email, phone, company, job_title, age, gender, city, country,
                    ticket_type, source, status, registered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"{first} {last}", email, f"+91-{random.randint(7000000000, 9999999999)}",
                    random.choice(COMPANIES), random.choice(JOB_TITLES),
                    random.randint(18, 65), random.choice(GENDERS), city, country,
                    ticket, source, "registered", reg_time.isoformat(),
                ),
            )
            attendee_id = cur.lastrowid

            # Higher-value tickets and earlier registrants check in more reliably
            base_prob = 0.55
            if ticket in ("VIP", "Speaker"):
                base_prob = 0.85
            if source == "walk_in":
                base_prob = 0.95  # walk-ins are by definition present

            if random.random() < base_prob:
                checkin_time = reg_time + timedelta(days=random.randint(0, 2), hours=random.randint(0, 10))
                conn.execute(
                    "INSERT INTO checkins (attendee_id, checkin_time, location, method) VALUES (?,?,?,?)",
                    (attendee_id, checkin_time.isoformat(), "Main Entrance", "kiosk"),
                )
                conn.execute("UPDATE attendees SET status = 'checked_in' WHERE id = ?", (attendee_id,))

        print(f"Seeded {len(used_emails)} attendees.")


# ==============================================================================
# Milestone 2: Venue & Speaker Operations demo data
# ==============================================================================
VENUES = [
    ("Grand Hall", 400, "Ground Floor", "AV,Livestream,Catering,Accessible"),
    ("Innovation Theatre", 220, "Ground Floor", "AV,Livestream,Accessible"),
    ("Summit Room A", 80, "1st Floor", "AV,Whiteboard"),
    ("Summit Room B", 80, "1st Floor", "AV,Whiteboard"),
    ("The Loft", 45, "2nd Floor", "Whiteboard,Accessible"),
    ("Workshop Studio", 60, "2nd Floor", "AV,Catering"),
]

SPEAKER_POOL = [
    ("Ananya Rao", "ananya.rao@speakers.io", "CloudNine Systems", "AI,Machine Learning,Cloud Architecture"),
    ("David Chen", "david.chen@speakers.io", "Nimbus Labs", "Product Strategy,Growth,Leadership"),
    ("Fatima Sheikh", "fatima.sheikh@speakers.io", "SecureStack", "Cybersecurity,Cloud Architecture,DevOps"),
    ("Marcus Webb", "marcus.webb@speakers.io", "Vertex Analytics", "Data Science,Machine Learning,AI"),
    ("Priya Nambiar", "priya.nambiar@speakers.io", "Freelance", "UX Design,Product Strategy,Accessibility"),
    ("Tomás Silva", "tomas.silva@speakers.io", "Orbit Systems", "DevOps,Cloud Architecture,Leadership"),
    ("Grace Kim", "grace.kim@speakers.io", "Bright Path", "Marketing,Growth,Branding"),
    ("Owen Fitzgerald", "owen.fitzgerald@speakers.io", "Cedar Health", "Healthtech,Data Science,AI"),
]

SESSION_TOPICS = [
    ("The Future of Generative AI in the Enterprise", "AI", "AI,Machine Learning"),
    ("Scaling Cloud Infrastructure for Hypergrowth", "Engineering", "Cloud Architecture,DevOps"),
    ("Zero Trust: Rethinking Cybersecurity from the Ground Up", "Security", "Cybersecurity"),
    ("Data-Driven Product Decisions", "Product", "Data Science,Product Strategy"),
    ("Designing for Accessibility at Scale", "Design", "UX Design,Accessibility"),
    ("Growth Loops That Actually Work", "Marketing", "Growth,Marketing"),
    ("Leading Engineering Teams Through Uncertainty", "Leadership", "Leadership"),
    ("AI in Healthcare: Promise and Pitfalls", "AI", "Healthtech,AI"),
    ("Building a Modern DevOps Culture", "Engineering", "DevOps"),
    ("Brand Storytelling for Technical Products", "Marketing", "Branding,Marketing"),
]


def seed_operations(num_sessions: int = 10):
    """Seeds venues, speakers, availability windows, and sessions for Milestone 2."""
    init_db()
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM venues").fetchone()["c"]
        if existing:
            print(f"Database already has {existing} venues - skipping operations seed.")
            return

        venue_ids = []
        for name, capacity, floor, amenities in VENUES:
            cur = conn.execute(
                "INSERT INTO venues (name, capacity, floor, amenities, status) VALUES (?,?,?,?,?)",
                (name, capacity, floor, amenities, "available"),
            )
            venue_ids.append(cur.lastrowid)
        # Take one room out of service to make utilization data more interesting.
        conn.execute("UPDATE venues SET status = 'maintenance' WHERE name = ?", ("Workshop Studio",))

        speaker_ids = []
        for name, email, company, expertise in SPEAKER_POOL:
            cur = conn.execute(
                "INSERT INTO speakers (name, email, company, bio, expertise, rating, status) VALUES (?,?,?,?,?,?,?)",
                (name, email, company, f"{name} is a recognized voice in {expertise.split(',')[0].lower()}.",
                 expertise, round(random.uniform(4.0, 5.0), 1), "confirmed"),
            )
            speaker_ids.append(cur.lastrowid)
            # Broad daytime availability across the event window so most auto-assignments succeed.
            # NOTE: kept timezone-naive on purpose - browser <input type="datetime-local"> values are
            # naive too, and Python raises TypeError when comparing naive vs. timezone-aware datetimes.
            # Every Milestone 2 timestamp (sessions, availability) must stay naive for that reason.
            avail_start = (datetime.now() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            avail_end = avail_start + timedelta(days=2, hours=2)
            conn.execute(
                "INSERT INTO speaker_availability (speaker_id, start_time, end_time) VALUES (?,?,?)",
                (cur.lastrowid, avail_start.isoformat(), avail_end.isoformat()),
            )

        # Build a schedule across two days, several tracks running in parallel - deliberately
        # leave a couple of overlaps in so the conflict-detection & optimizer have something to do.
        event_day1 = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        slots = [event_day1 + timedelta(hours=h) for h in (0, 0, 2, 2, 4, 4)]  # two parallel tracks, 3 time blocks
        slots += [event_day1 + timedelta(days=1, hours=h) for h in (0, 0, 2, 2)]

        random.shuffle(SESSION_TOPICS)
        for i in range(min(num_sessions, len(SESSION_TOPICS), len(slots))):
            title, track, expertise = SESSION_TOPICS[i]
            start = slots[i]
            end = start + timedelta(minutes=45)
            expected = random.choice([30, 50, 75, 120, 180])
            topic = expertise.split(",")[0]

            venue, _ = venue_agent_recommend(conn, start.isoformat(), end.isoformat(), expected)
            speaker, _ = speaker_agent_recommend(conn, start.isoformat(), end.isoformat(), topic)

            conn.execute(
                """INSERT INTO sessions
                   (title, description, track, speaker_id, venue_id, start_time, end_time,
                    expected_attendance, required_amenities, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (title, f"A session on {topic.lower()}.", track,
                 speaker["id"] if speaker else None, venue["id"] if venue else None,
                 start.isoformat(), end.isoformat(), expected, "AV", "scheduled", now_iso()),
            )

        # Intentionally introduce one venue double-booking and one speaker double-booking
        # so the Overview -> Session Analytics conflict panel has real data to show.
        first_session = conn.execute("SELECT * FROM sessions ORDER BY id LIMIT 1").fetchone()
        if first_session:
            conn.execute(
                """INSERT INTO sessions
                   (title, description, track, speaker_id, venue_id, start_time, end_time,
                    expected_attendance, required_amenities, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("Surprise Lightning Talks", "Unplanned overlap - demonstrates conflict detection.", "General",
                 first_session["speaker_id"], first_session["venue_id"],
                 first_session["start_time"], first_session["end_time"], 40, "", "conflict", now_iso()),
            )

        print(f"Seeded {len(venue_ids)} venues, {len(speaker_ids)} speakers, "
              f"and {min(num_sessions, len(SESSION_TOPICS))+1} sessions.")


# Local aliases to avoid a hard import-order dependency at module load time.
def venue_agent_recommend(conn, start_time, end_time, expected_attendance):
    import venue_agent
    return venue_agent.recommend_venue(conn, start_time, end_time, expected_attendance)


def speaker_agent_recommend(conn, start_time, end_time, topic):
    import speaker_agent
    return speaker_agent.recommend_speaker(conn, start_time, end_time, topic)


# ==============================================================================
# Milestone 3: Sponsorship & Incident Management demo data
# ==============================================================================
SPONSORS = [
    # name, tier, industry, contact_name, contact_email, contract_value, status
    ("Vertex Cloud", "Platinum", "Technology", "Nadia Farouk", "nadia.farouk@vertexcloud.com", 50000, "confirmed"),
    ("Nimbus Analytics", "Gold", "Technology", "Ravi Desai", "ravi.desai@nimbusanalytics.io", 25000, "confirmed"),
    ("Bright Path Media", "Silver", "Media & Entertainment", "Lena Ostrowski", "lena.ostrowski@brightpathmedia.com", 10000, "confirmed"),
    ("CedarWorks", "Bronze", "Manufacturing", "Tomás Silva", "tomas.silva@cedarworks.dev", 4000, "confirmed"),
    ("Orbit Robotics", "Gold", "Technology", "Wei Zhang", "wei.zhang@orbitrobotics.ai", 22000, "confirmed"),
    # Prospects: identified as good fits but not yet approached - demo data for the new
    # search & approach workflow.
    ("Meridian Health Group", "Gold", "Healthcare", "Dr. Amara Okonkwo", "amara.okonkwo@meridianhealth.com", 20000, "prospect"),
    ("Solstice Financial", "Platinum", "Finance", "Marcus Webb", "marcus.webb@solsticefinancial.com", 45000, "prospect"),
    ("Harborline Retail Co.", "Silver", "Retail", "Priya Nambiar", "priya.nambiar@harborline.com", 9000, "prospect"),
]

DELIVERABLE_TEMPLATES = [
    "Logo on main stage banner", "Booth space setup (Hall A)", "Mention in opening keynote",
    "Sponsored session slot", "Logo on event app & website", "Swag bag insert",
]

INCIDENT_TEMPLATES = [
    ("Attendee medical assistance requested", "Medical", "high", "Hall A entrance"),
    ("Badge printer offline", "Technical", "medium", "Registration Desk"),
    ("Wi-Fi congestion in Summit Rooms", "Technical", "low", "1st Floor"),
    ("Unauthorized person at speaker entrance", "Security", "critical", "Backstage - Innovation Theatre"),
    ("Catering delivery delayed", "Logistics", "low", "Grand Hall"),
    ("Spilled liquid near power strips", "Safety", "medium", "The Loft"),
]


def seed_sponsorship_incidents(num_incidents: int = 6):
    """Seeds sponsors (with deliverables + engagement) and incidents for Milestone 3."""
    init_db()
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM sponsors").fetchone()["c"]
        if existing:
            print(f"Database already has {existing} sponsors - skipping sponsorship/incident seed.")
            return

        for name, tier, industry, contact_name, contact_email, value, status in SPONSORS:
            cur = conn.execute(
                "INSERT INTO sponsors (name, tier, industry, contact_name, contact_email, contract_value, status, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, tier, industry, contact_name, contact_email, value, status, None, now_iso()),
            )
            sponsor_id = cur.lastrowid

            # Prospects haven't signed on yet, so they don't have contracted deliverables or
            # real engagement data - that only makes sense once a sponsor is pending/confirmed.
            if status == "prospect":
                continue

            # 2-3 deliverables per sponsor, a realistic mix of statuses.
            num_deliv = random.randint(2, 3)
            for desc in random.sample(DELIVERABLE_TEMPLATES, num_deliv):
                d_status = random.choices(["pending", "in_progress", "completed"], weights=[3, 2, 3])[0]
                conn.execute(
                    "INSERT INTO sponsor_deliverables (sponsor_id, description, status, due_date) VALUES (?,?,?,?)",
                    (sponsor_id, desc, d_status, None),
                )

            # Engagement logs scaled roughly by tier so Platinum/Gold sponsors look more active -
            # except one Gold sponsor deliberately left under-logged to trigger the "underperforming" insight.
            if name == "Orbit Robotics":
                base = {"booth_visits": 4, "leads": 1, "social_mentions": 1, "impressions": 50}
            else:
                tier_multiplier = {"Platinum": 6, "Gold": 4, "Silver": 2, "Bronze": 1}[tier]
                base = {
                    "booth_visits": tier_multiplier * random.randint(15, 25),
                    "leads": tier_multiplier * random.randint(3, 8),
                    "social_mentions": tier_multiplier * random.randint(2, 6),
                    "impressions": tier_multiplier * random.randint(200, 500),
                }
            for metric_type, value in base.items():
                conn.execute(
                    "INSERT INTO sponsor_engagement (sponsor_id, metric_type, value, logged_at) VALUES (?,?,?,?)",
                    (sponsor_id, metric_type, value, now_iso()),
                )

        # Incidents: a healthy mix of open/in_progress/resolved, plus one deliberately stale
        # critical incident so the Incident Agent's alert feed has something real to show.
        # NOTE: must stay timezone-aware here to match now_iso() - incidents are always
        # server-timestamped (never a naive browser <input type="datetime-local"> value like
        # sessions/availability are), so there's no reason to special-case them as naive.
        now = datetime.now(timezone.utc)
        for i, (title, category, severity, location) in enumerate(random.sample(INCIDENT_TEMPLATES, min(num_incidents, len(INCIDENT_TEMPLATES)))):
            created = now - timedelta(minutes=random.randint(5, 90))
            status = random.choices(["open", "in_progress", "resolved"], weights=[2, 2, 3])[0]
            resolved_at = (created + timedelta(minutes=random.randint(10, 40))).isoformat() if status == "resolved" else None
            conn.execute(
                """INSERT INTO incidents
                   (title, description, category, severity, location, status, reported_by, assigned_to, created_at, updated_at, resolved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (title, f"Reported near {location}.", category, severity, location, status,
                 "Staff Radio", "Ops Team" if status != "open" else None,
                 created.isoformat(), created.isoformat(), resolved_at),
            )

        # Deliberately stale critical incident (created well past its 15-minute budget, still open).
        stale_created = (now - timedelta(minutes=45)).isoformat()
        conn.execute(
            """INSERT INTO incidents
               (title, description, category, severity, location, status, reported_by, assigned_to, created_at, updated_at, resolved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("Fire alarm triggered near kitchen", "Smoke detected, unconfirmed cause.", "Safety", "critical",
             "Grand Hall - Catering Area", "open", "Venue Staff", None, stale_created, stale_created, None),
        )

        print(f"Seeded {len(SPONSORS)} sponsors (with deliverables & engagement) and "
              f"{min(num_incidents, len(INCIDENT_TEMPLATES)) + 1} incidents.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    seed(n)
    seed_operations()
    seed_sponsorship_incidents()
