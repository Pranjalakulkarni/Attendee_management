#!/usr/bin/env bash
# Backup and recovery (Milestone 4, Objective 9).
#
# SQLite is a single file, so backup is just "copy the file" - this script does
# that safely (using SQLite's own backup command rather than a raw file copy,
# so it won't produce a corrupt snapshot if a write is in flight) and prunes
# anything older than 14 days.
#
# Usage:
#   ./scripts/backup_db.sh                    # backs up backend/../data/attendees.db
#   DATABASE_PATH=/custom/path.db ./scripts/backup_db.sh
#
# Restore:
#   cp backups/attendees-YYYY-MM-DDTHH-MM-SS.db data/attendees.db
#
# Run this on a schedule (cron, or your platform's scheduled-job feature) for
# real production use, e.g. hourly:
#   0 * * * * /path/to/scripts/backup_db.sh >> /var/log/gatehouse-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

DB_PATH="${DATABASE_PATH:-$PROJECT_ROOT/data/attendees.db}"
BACKUP_DIR="$PROJECT_ROOT/backups"
TIMESTAMP=$(date +"%Y-%m-%dT%H-%M-%S")
BACKUP_FILE="$BACKUP_DIR/attendees-$TIMESTAMP.db"

if [ ! -f "$DB_PATH" ]; then
    echo "No database found at $DB_PATH - nothing to back up."
    exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Backing up $DB_PATH -> $BACKUP_FILE"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

echo "Pruning backups older than 14 days..."
find "$BACKUP_DIR" -name "attendees-*.db" -mtime +14 -delete

echo "Done. $(ls "$BACKUP_DIR" | wc -l) backup(s) retained."
