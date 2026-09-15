"""
database.py
Lightweight SQLite persistence layer for the Attendee Management module.
No external DB server needed for the prototype - swap for Postgres later
by replacing the connection logic here; the SQL is intentionally vanilla.
"""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone

_DEFAULT_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "attendees.db"))
# Configurable for production deployment / test isolation (Milestone 4, Objectives 6 & 9) -
# defaults to the existing on-disk location so nothing changes for anyone already running this.
DB_PATH = os.environ.get("DATABASE_PATH", _DEFAULT_DB_PATH)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL mode (Objective 8, Performance): lets reads proceed concurrently with a writer instead
    # of blocking, which matters here since the Executive Dashboard polls every 15s while other
    # tabs may be writing (check-ins, incident updates). Default SQLite journal mode blocks readers
    # during a write; WAL doesn't. Safe to set on every connection - SQLite persists the mode on
    # the database file after the first call.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS attendees (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT NOT NULL UNIQUE,
                phone           TEXT,
                company         TEXT,
                job_title       TEXT,
                age             INTEGER,
                gender          TEXT,
                city            TEXT,
                country         TEXT,
                ticket_type     TEXT DEFAULT 'General',
                source          TEXT DEFAULT 'web_form',
                status          TEXT DEFAULT 'registered',
                registered_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                attendee_id     INTEGER NOT NULL,
                checkin_time    TEXT NOT NULL,
                checkout_time   TEXT,
                location        TEXT DEFAULT 'Main Entrance',
                method          TEXT DEFAULT 'manual',
                FOREIGN KEY (attendee_id) REFERENCES attendees(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checkins_attendee ON checkins(attendee_id);
            CREATE INDEX IF NOT EXISTS idx_attendees_email ON attendees(email);
            CREATE INDEX IF NOT EXISTS idx_attendees_source ON attendees(source);
            CREATE INDEX IF NOT EXISTS idx_attendees_registered_at ON attendees(registered_at);
            CREATE INDEX IF NOT EXISTS idx_checkins_checkin_time ON checkins(checkin_time);

            -- ============================================================
            -- Milestone 2: Venue & Speaker Operations
            -- ============================================================
            CREATE TABLE IF NOT EXISTS venues (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL UNIQUE,
                capacity        INTEGER NOT NULL,
                floor           TEXT,
                amenities       TEXT DEFAULT '',   -- comma-separated tags, e.g. "AV,Wifi,Catering"
                status          TEXT DEFAULT 'available',  -- available | maintenance | closed
                notes           TEXT
            );

            CREATE TABLE IF NOT EXISTS speakers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT NOT NULL UNIQUE,
                company         TEXT,
                bio             TEXT,
                expertise       TEXT DEFAULT '',   -- comma-separated topic tags
                rating          REAL DEFAULT 4.5,
                status          TEXT DEFAULT 'confirmed'  -- confirmed | pending | cancelled
            );

            CREATE TABLE IF NOT EXISTS speaker_availability (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                speaker_id      INTEGER NOT NULL,
                start_time      TEXT NOT NULL,
                end_time        TEXT NOT NULL,
                FOREIGN KEY (speaker_id) REFERENCES speakers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                title               TEXT NOT NULL,
                description         TEXT,
                track               TEXT DEFAULT 'General',
                speaker_id          INTEGER,
                venue_id            INTEGER,
                start_time          TEXT NOT NULL,
                end_time            TEXT NOT NULL,
                expected_attendance INTEGER DEFAULT 0,
                required_amenities  TEXT DEFAULT '',
                status              TEXT DEFAULT 'scheduled',  -- scheduled | conflict | unassigned | cancelled
                notes               TEXT,
                created_at          TEXT NOT NULL,
                FOREIGN KEY (speaker_id) REFERENCES speakers(id) ON DELETE SET NULL,
                FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_speaker_avail_speaker ON speaker_availability(speaker_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_venue ON sessions(venue_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_speaker ON sessions(speaker_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(start_time, end_time);

            -- ============================================================
            -- Milestone 3: Sponsorship & Incident Management
            -- ============================================================
            CREATE TABLE IF NOT EXISTS sponsors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL UNIQUE,
                tier            TEXT DEFAULT 'Bronze',   -- Platinum | Gold | Silver | Bronze
                industry        TEXT,                     -- e.g. Technology, Finance, Healthcare - used for prospect search
                contact_name    TEXT,
                contact_email   TEXT,
                contract_value  REAL DEFAULT 0,
                status          TEXT DEFAULT 'confirmed',  -- prospect | pending | confirmed | cancelled
                notes           TEXT,
                approached_at   TEXT,                      -- when the Sponsorship Agent's outreach draft was generated
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sponsor_deliverables (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                sponsor_id      INTEGER NOT NULL,
                description     TEXT NOT NULL,
                status          TEXT DEFAULT 'pending',  -- pending | in_progress | completed
                due_date        TEXT,
                FOREIGN KEY (sponsor_id) REFERENCES sponsors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sponsor_engagement (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                sponsor_id      INTEGER NOT NULL,
                metric_type     TEXT NOT NULL,   -- booth_visits | leads | social_mentions | impressions
                value           INTEGER NOT NULL DEFAULT 0,
                logged_at       TEXT NOT NULL,
                FOREIGN KEY (sponsor_id) REFERENCES sponsors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                description     TEXT,
                category        TEXT DEFAULT 'Other',    -- Medical | Security | Technical | Logistics | Other
                severity        TEXT DEFAULT 'low',       -- low | medium | high | critical
                location        TEXT,
                status          TEXT DEFAULT 'open',       -- open | in_progress | resolved
                reported_by     TEXT,
                assigned_to     TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                resolved_at     TEXT,
                auto_escalated  INTEGER DEFAULT 0    -- 1 if the Incident Agent bumped severity automatically (no human click)
            );

            CREATE INDEX IF NOT EXISTS idx_sponsor_engagement_sponsor ON sponsor_engagement(sponsor_id);
            CREATE INDEX IF NOT EXISTS idx_sponsor_deliverables_sponsor ON sponsor_deliverables(sponsor_id);
            CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
            CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
            CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at);
            """
        )

        # Lightweight migration: databases created before this column existed won't have it,
        # and "CREATE TABLE IF NOT EXISTS" doesn't retroactively add columns to an existing table.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)").fetchall()}
        if "auto_escalated" not in existing_cols:
            conn.execute("ALTER TABLE incidents ADD COLUMN auto_escalated INTEGER DEFAULT 0")

        sponsor_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sponsors)").fetchall()}
        if "industry" not in sponsor_cols:
            conn.execute("ALTER TABLE sponsors ADD COLUMN industry TEXT")
        if "approached_at" not in sponsor_cols:
            conn.execute("ALTER TABLE sponsors ADD COLUMN approached_at TEXT")


def now_iso():
    return datetime.now(timezone.utc).isoformat()
