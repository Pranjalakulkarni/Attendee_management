# Cloud deployment (Milestone 4, Objective 9 - "Deploy a production-ready platform").
# Build:  docker build -t gatehouse .
# Run:    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v gatehouse_data:/app/data gatehouse
#
# Mount a volume at /app/data (as shown above) so the SQLite database survives
# container restarts/redeploys - without it, every new container starts fresh.

FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

WORKDIR /app/backend

ENV PORT=8000
EXPOSE 8000

# Seeds demo data only if the database doesn't already exist (e.g. a fresh volume),
# so redeploys against an existing volume never wipe real data. Then starts the
# server with the platform-provided $PORT if set, falling back to 8000.
CMD sh -c '\
    DB_FILE="${DATABASE_PATH:-/app/data/attendees.db}"; \
    if [ ! -f "$DB_FILE" ]; then \
        echo "No existing database found at $DB_FILE - seeding demo data..."; \
        python seed_data.py 150; \
    fi; \
    uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"'
