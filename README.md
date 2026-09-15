# Gatehouse — Intelligent Event Management Platform

A working prototype of a full event-operations platform built up across four
milestones: attendee management, venue & speaker operations, sponsorship &
incident management, and — this milestone — an Event Intelligence Engine
that orchestrates everything above it into one executive dashboard.

FastAPI backend + a single-page HTML/JS organizer dashboard. No build step,
no external services required to run it.

## Milestones at a glance

| Milestone | Delivered |
|---|---|
| **1 — Attendee Management** | Registration, CSV/API import, real-time check-in over WebSocket, demographics/behavior analytics, rule-based + optional Claude-narrative insights |
| **2 — Venue & Speaker Operations** | Venue Agent (allocation, conflict detection, live availability) + Speaker Agent (matching, availability windows, conflict detection), scheduling workflow with an auto-optimizer, session analytics |
| **3 — Sponsorship & Incident Management** | Sponsorship Agent (tiers, deliverables, engagement tracking, prospect search & outreach drafting) + Incident Agent (lifecycle, automatic escalation, live alert feed), CSV report exports |
| **4 — Event Intelligence & Enterprise Deployment** | Event Intelligence Engine that orchestrates every agent above, an Executive Dashboard (KPIs, live trends, cross-module risk detection, recommendations), a real end-to-end test suite, and production-readiness work (auth, security headers, rate limiting, logging, caching, Docker, CI/CD, backups) |

For the full API reference, architecture diagram, data model, and security
review, see **[TECHNICAL_DOCS.md](./TECHNICAL_DOCS.md)**.

## Project structure

```
attendee_management__final/
├── backend/
│   ├── main.py                 FastAPI app: routes, middleware, WebSocket manager
│   ├── database.py             SQLite connection + full schema (all 4 milestones)
│   ├── schemas.py              Pydantic request/response models
│   ├── seed_data.py            Generates realistic demo data for every module
│   ├── insights.py             M1: attendee analytics + rule-based/LLM insights
│   ├── venue_agent.py          M2: venue allocation, conflicts, live availability
│   ├── speaker_agent.py        M2: speaker matching, availability, conflicts
│   ├── session_analytics.py    M2: session/scheduling analytics + insights
│   ├── sponsor_agent.py        M3: sponsor tiers, deliverables, search & outreach
│   ├── incident_agent.py       M3: incident lifecycle, auto-escalation, alerts
│   ├── ops_analytics.py        M3: combined sponsorship+incident analytics
│   ├── intelligence_engine.py  M4: orchestrates every agent above, KPIs, risks
│   ├── tests/test_e2e.py       Self-contained end-to-end test suite
│   └── requirements.txt
├── frontend/index.html          Dashboard (vanilla JS, Chart.js, no build step)
├── data/attendees.db            Created automatically on first run
├── scripts/backup_db.sh         SQLite-safe backup script
├── .github/workflows/ci.yml     Runs the E2E suite on every push/PR
├── Dockerfile
├── .env.example
├── README.md
└── TECHNICAL_DOCS.md
```

## Running it

```bash
cd attendee_management__final/backend
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# populate demo data for every module (attendees, venues, speakers, sessions,
# sponsors, incidents) so the dashboard isn't empty
python seed_data.py 150

# optional: enable richer AI narrative insights on the three AI Insights tabs
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000**. The navigation is grouped into four
sections: **Executive Dashboard**, **Attendee Management**, **Venue &
Speaker Ops**, and **Sponsorship & Incidents**.

## Running the tests

```bash
cd backend
python tests/test_e2e.py
```

A real end-to-end suite (61 checks): boots its own throwaway server on a
disposable copy of the database (never touches your real
`data/attendees.db`), exercises functional, integration, AI/agent, API,
workflow, dashboard, performance, and security testing across all four
milestones, then tears itself down. Exits 0/1, safe for CI as-is (see
`.github/workflows/ci.yml`).

## Production deployment

**Environment variables** (see `.env.example` for the full list):

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude-narrative insights. Everything works without it. | unset |
| `ALLOWED_ORIGINS` | CORS allow-list, comma-separated. **Lock down before going live.** | `*` |
| `DATABASE_PATH` | Absolute path to the SQLite file (e.g. a mounted volume). | `data/attendees.db` |
| `API_KEY` | Optional shared-secret API auth (off by default). See TECHNICAL_DOCS.md. | unset |
| `LOG_LEVEL` | Python logging level. | `INFO` |

**Running the server** — drop `--reload`, run multiple workers:

```bash
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

**Or via Docker:**

```bash
docker build -t gatehouse .
docker run -p 8000:8000 -v gatehouse_data:/app/data gatehouse
```

**Health checks**: `GET /api/health` — wire into your load balancer's
liveness/readiness probes.

**Backups**: `./scripts/backup_db.sh` — safe SQLite backup, prune old ones
automatically. Schedule it with cron for real production use.

**What's already hardened**: security headers, rate limiting, structured
logging, a global exception handler that never leaks internals, WAL-mode
SQLite + indexes + response caching for performance, optional API-key auth.

**What's intentionally not done yet** (see TECHNICAL_DOCS.md §7 for the
full security review): no full user-login system with roles/sessions —
that's the top priority before any public-facing deployment. SQLite
instead of Postgres (deliberate, for a zero-dependency prototype —
`database.py` isolates all SQL so this is a contained swap later).
Single-event scope (multi-event would need an `events` table + FK
throughout).

## Trying the real-time features

- **Check-in feed**: two tabs, check someone in from one, watch **Overview
  → Live Arrivals** update instantly in the other — WebSocket push, not polling.
- **Incident alerts**: the Incident Agent re-checks every open incident
  every 30 seconds server-side and auto-escalates anything past its
  severity's response budget, with zero user action required.
- **Executive Dashboard**: create a session starting soon with expected
  attendance near a venue's capacity, and watch the "Operational Risk
  Alerts" board flag the crowding risk automatically within ~15 seconds.
