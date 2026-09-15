"""
tests/test_e2e.py
End-to-end test suite - Milestone 4, Objective 6 ("Perform End-to-End Testing").

Boots a real uvicorn server against a disposable copy of the database (never
touches your real data/attendees.db), runs HTTP requests against every major
endpoint across all four milestones, checks both success and failure paths,
and exercises real write workflows (not just "does it 200").

Run it with:
    cd backend
    python tests/test_e2e.py

No new dependencies: uses only `requests`, which is already in requirements.txt.
Exits with code 0 if everything passes, 1 if anything fails - safe to wire
into a CI pipeline as-is.
"""

import os
import sys
import time
import shutil
import signal
import subprocess
import tempfile

import requests

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8931  # deliberately non-default, to avoid colliding with a real server you might have running
BASE = f"http://127.0.0.1:{PORT}"

PASS, FAIL = [], []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  OK   {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


def get(path, **kw):
    return requests.get(BASE + path, timeout=10, **kw)


def post(path, **kw):
    return requests.post(BASE + path, timeout=10, **kw)


def put(path, **kw):
    return requests.put(BASE + path, timeout=10, **kw)


def delete(path, **kw):
    return requests.delete(BASE + path, timeout=10, **kw)


def wait_for_server(timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            if get("/api/health").status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    return False


def run_all_checks():
    # ---------------- Milestone 1: Attendee Management ----------------
    check("homepage loads", get("/").status_code == 200)
    check("health check reports ok", get("/api/health").json().get("status") == "ok")
    check("attendees list", get("/api/attendees?limit=5").status_code == 200)
    check("analytics summary", get("/api/analytics/summary").status_code == 200)
    check("insights", get("/api/insights").status_code == 200)

    reg = post("/api/attendees", json={"name": "E2E Test User", "email": "e2e.test@example.com"})
    check("register new attendee -> 201", reg.status_code == 201)
    attendee_id = reg.json().get("id") if reg.status_code == 201 else None

    if attendee_id:
        checkin = post("/api/checkin/lookup", json={"email": "e2e.test@example.com"})
        check("check in the attendee we just registered", checkin.status_code == 200)
        dup = post(f"/api/checkin/{attendee_id}", json={})
        check("double check-in correctly rejected", dup.status_code == 409)

    # ---------------- Milestone 2: Venue & Speaker Operations ----------------
    check("venues list", get("/api/venues").status_code == 200)
    check("venues live-status", get("/api/venues/live-status").status_code == 200)
    check("venue 404 for bad id", get("/api/venues/999999").status_code == 404)
    check("speakers list", get("/api/speakers").status_code == 200)
    check("sessions list", get("/api/sessions").status_code == 200)
    check("scheduling conflicts", get("/api/scheduling/conflicts").status_code == 200)
    check("session analytics", get("/api/session-analytics/summary").status_code == 200)

    sess = post("/api/sessions", json={
        "title": "E2E Test Session", "track": "QA", "start_time": "2027-01-01T10:00:00",
        "end_time": "2027-01-01T10:30:00", "expected_attendance": 10, "auto_assign": False,
    })
    check("create session without auto-assign -> unassigned", sess.status_code == 201 and sess.json().get("status") == "unassigned")

    # ---------------- Milestone 3: Sponsorship & Incident Management ----------------
    check("sponsors list", get("/api/sponsors").status_code == 200)
    check("sponsor search endpoint", get("/api/sponsors/search?status=prospect").status_code == 200)
    check("sponsor industries list", get("/api/sponsors/industries").status_code == 200)
    check("incidents list", get("/api/incidents").status_code == 200)
    check("incident alerts feed", get("/api/incidents/alerts").status_code == 200)
    check("ops analytics summary", get("/api/ops-analytics/summary").status_code == 200)
    check("sponsor csv report downloads", get("/api/reports/sponsors.csv").status_code == 200)
    check("incident csv report downloads", get("/api/reports/incidents.csv").status_code == 200)

    inc = post("/api/incidents", json={"title": "E2E Test Incident", "category": "Technical", "severity": "low"})
    check("report new incident -> 201", inc.status_code == 201)
    incident_id = inc.json().get("id") if inc.status_code == 201 else None
    if incident_id:
        esc = post(f"/api/incidents/{incident_id}/escalate")
        check("escalate incident bumps severity low->medium", esc.status_code == 200 and esc.json().get("severity") == "medium")
        res = post(f"/api/incidents/{incident_id}/resolve")
        check("resolve incident -> status resolved", res.status_code == 200 and res.json().get("status") == "resolved")

    sp = post("/api/sponsors", json={"name": "E2E Test Sponsor", "tier": "Bronze", "status": "prospect"})
    check("create prospect sponsor -> 201", sp.status_code == 201)
    sponsor_id = sp.json().get("id") if sp.status_code == 201 else None
    if sponsor_id:
        approach = post(f"/api/sponsors/{sponsor_id}/approach")
        check("approach sponsor returns a draft + flips to pending",
              approach.status_code == 200 and "subject" in approach.json() and approach.json()["sponsor"]["status"] == "pending")
        delete(f"/api/sponsors/{sponsor_id}")  # cleanup

    # ---------------- Milestone 4: Event Intelligence Engine ----------------
    check("intelligence summary", get("/api/intelligence/summary").status_code == 200)
    check("intelligence risks", get("/api/intelligence/risks").status_code == 200)
    check("intelligence recommendations", get("/api/intelligence/recommendations").status_code == 200)
    intel = get("/api/intelligence/kpis")
    check("intelligence kpis has health_score", intel.status_code == 200 and "health_score" in intel.json())
    check("agent orchestration lists all 6 agents", len(get("/api/intelligence/summary").json().get("agents_orchestrated", [])) == 6)

    # ---------------- Security & reliability: headers ----------------
    headers = get("/").headers
    check("security header X-Content-Type-Options present", headers.get("x-content-type-options") == "nosniff")
    check("security header X-Frame-Options present", headers.get("x-frame-options") == "DENY")

    # ---------------- Dashboard testing ----------------
    # This app has no build step - the dashboard's markup is what's actually served, so we can
    # verify it directly: every tab/section the UI depends on must be present in the served HTML.
    homepage_html = get("/").text
    for element_id in ["panel-executive-dashboard", "panel-overview", "panel-venues", "panel-speakers",
                        "panel-scheduling", "panel-sponsors", "panel-incidents", "panel-ops-analytics",
                        "healthScore", "riskAlertsList", "execRecommendations", "agentOrchestrationList"]:
        check(f"dashboard markup includes #{element_id}", f'id="{element_id}"' in homepage_html)
    for section in ["executive", "attendees", "venue-speaker", "sponsorship"]:
        check(f"dashboard nav includes '{section}' section", f'data-section="{section}"' in homepage_html)

    # ---------------- Performance testing ----------------
    # The intelligence summary orchestrates nearly every agent in the app - it's the heaviest
    # read this API serves and the one the Executive Dashboard polls most often, so it's the
    # one worth timing explicitly. A cold call should still be fast against a small demo DB;
    # a call within the 5s cache window should be near-instant.
    t0 = time.time()
    first_call = get("/api/intelligence/summary")
    cold_ms = (time.time() - t0) * 1000
    check(f"intelligence summary cold call completes in a reasonable time ({cold_ms:.0f}ms)", cold_ms < 3000)

    t0 = time.time()
    second_call = get("/api/intelligence/summary")
    cached_ms = (time.time() - t0) * 1000
    check(f"intelligence summary cache hit is fast ({cached_ms:.0f}ms)", cached_ms < 200)
    check("cache hit returns identical generated_at (proves it's cached, not recomputed)",
          first_call.json().get("generated_at") == second_call.json().get("generated_at"))

    # ---------------- Security testing: rate limiting ----------------
    # The limiter allows 240 requests/minute/IP. Firing 60 rapid requests should comfortably
    # stay under that (proving normal/heavy dashboard use is never falsely blocked) without
    # spending the whole test budget hammering the server.
    statuses = [get("/api/health").status_code for _ in range(60)]
    check("60 rapid requests all succeed (rate limit doesn't false-positive on normal use)",
          all(s == 200 for s in statuses), detail=f"got: {set(statuses)}")

    # ---------------- Error handling ----------------
    check("malformed attendee registration is rejected with 422, not a 500",
          post("/api/attendees", json={"name": "No Email Field"}).status_code == 422)
    check("unknown route returns a clean 404", get("/api/this-route-does-not-exist").status_code == 404)

    # ---------------- Route-ordering regression guard ----------------
    # These literal sub-paths have broken before when declared after their {id} sibling route.
    # If this ever regresses, these will fail with 422 (id parsed as the literal string) instead of 200.
    check("route order: /api/venues/available not swallowed by /{id}",
          get("/api/venues/available?start_time=2027-01-01T10:00:00&end_time=2027-01-01T11:00:00").status_code == 200)
    check("route order: /api/incidents/alerts not swallowed by /{id}", get("/api/incidents/alerts").status_code == 200)
    check("route order: /api/sponsors/search not swallowed by /{id}", get("/api/sponsors/search").status_code == 200)


def main():
    tmp_dir = tempfile.mkdtemp(prefix="gatehouse_e2e_")
    tmp_db_dir = os.path.join(tmp_dir, "data")
    os.makedirs(tmp_db_dir, exist_ok=True)

    env = os.environ.copy()
    env["DATABASE_PATH"] = os.path.join(tmp_db_dir, "attendees.db")

    print(f"Seeding a disposable test database at {env['DATABASE_PATH']} ...")
    subprocess.run([sys.executable, "seed_data.py", "20"], cwd=BACKEND_DIR, env=env, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"Starting test server on port {PORT} ...")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        if not wait_for_server():
            print("Server never became healthy - aborting.")
            sys.exit(1)

        print("Server is up. Running checks...\n")
        run_all_checks()
    finally:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed.")
    if FAIL:
        print("Failed checks:")
        for name in FAIL:
            print(f"  - {name}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
