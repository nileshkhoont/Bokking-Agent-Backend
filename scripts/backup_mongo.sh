#!/usr/bin/env bash
# Daily MongoDB backup for the self-hosted "mongo" container (see DEPLOYMENT.md Step 3.5).
# Meant to be run by cron on the VPS itself, not inside a container.
#
# What it does:
#   1. Dumps this deployment's own database (mongodump, gzipped) straight from the running
#      container to a timestamped file in BACKUP_DIR on the host.
#   2. Deletes backups older than RETENTION_DAYS, so this directory doesn't grow forever.
#   3. Appends one line to backup.log recording success or failure.
#
# Fully portable, deliberately — nothing hospital/deployment-specific is hardcoded here. Every
# value below comes from THIS script's own location and THIS deployment's own .env file, so
# copying this whole repo into a second /var/www/<other-hospital> directory (see DEPLOYMENT.md's
# "Deploying Additional Hospitals on the Same VPS" section) needs zero edits to this file — only
# that deployment's own .env differs.
#
# Usage: backup_mongo.sh  (no arguments)
# See DEPLOYMENT.md Step 3.5.5 for how to schedule this with cron, and how to restore from a
# backup it created.

set -euo pipefail

# The project root is wherever THIS script actually lives, not a hardcoded path — this file is
# always at <project root>/scripts/backup_mongo.sh, so its grandparent directory is the project
# root regardless of what that deployment's directory is named.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "$(date -Is) FAILED — $ENV_FILE not found" >&2
  exit 1
fi

# Small helper: read one KEY=value line out of .env, or fall back to a default if it's missing/
# blank. Doesn't source the whole file — that would also pull in every other secret in .env into
# this script's environment, which it has no reason to need.
read_env() {
  local key="$1" default="$2" value
  value=$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d '=' -f2-)
  echo "${value:-$default}"
}

DB_NAME=$(read_env MONGODB_DB_NAME "ai_calling_agent")
BACKUP_DIR=$(read_env BACKUP_DIR "/var/backups/${DB_NAME}-mongo")
RETENTION_DAYS=$(read_env BACKUP_RETENTION_DAYS "14")
MONGO_USER=$(read_env MONGO_INITDB_ROOT_USERNAME "")
MONGO_PASS=$(read_env MONGO_INITDB_ROOT_PASSWORD "")

mkdir -p "$BACKUP_DIR"
LOG_FILE="$BACKUP_DIR/backup.log"
log() { echo "$(date -Is) $1" >> "$LOG_FILE"; }

if [ -z "$MONGO_USER" ] || [ -z "$MONGO_PASS" ]; then
  log "FAILED — MONGO_INITDB_ROOT_USERNAME/PASSWORD empty in $ENV_FILE"
  exit 1
fi

TIMESTAMP=$(date +%F_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}-${TIMESTAMP}.gz"

cd "$PROJECT_DIR"

# -T disables pseudo-TTY allocation — required here: with a TTY attached, `docker compose exec`
# can corrupt mongodump's binary gzip output as it streams through; -T gives a clean raw pipe.
# COMPOSE_PROJECT_NAME (if this deployment set one in .env) is picked up automatically by
# `docker compose` itself from .env — not passed explicitly here — so this always targets THIS
# deployment's own mongo container, never a different hospital's, even on a shared VPS.
if docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T mongo \
    mongodump --username "$MONGO_USER" --password "$MONGO_PASS" --authenticationDatabase admin \
    --db "$DB_NAME" --archive --gzip > "$BACKUP_FILE" 2>>"$LOG_FILE"; then
  SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
  log "OK — $BACKUP_FILE ($SIZE)"
else
  log "FAILED — mongodump exited non-zero, see error above"
  rm -f "$BACKUP_FILE"   # don't keep a partial/empty file around looking like a valid backup
  exit 1
fi

# Prune anything older than RETENTION_DAYS
find "$BACKUP_DIR" -name "${DB_NAME}-*.gz" -mtime "+${RETENTION_DAYS}" -delete
