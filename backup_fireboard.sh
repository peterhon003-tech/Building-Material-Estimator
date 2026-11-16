#!/bin/sh
# ============================================================
#  Fire Board Estimator - database backup (Linux / WSL)
#
#  - Dumps the whole PostgreSQL database to BACKUP_DIR/daily
#  - The first backup of each month is also kept in "monthly"
#  - Results are written to backup.log; exit code 1 on failure
#  - Run as root from cron, e.g. every hour:
#      5 * * * * /opt/fireboard/backup_fireboard.sh
# ============================================================

# ---------- Settings ----------
APP_DIR=/opt/fireboard
BACKUP_DIR=/mnt/c/fireboard_backup      # = C:\fireboard_backup on Windows
DAILY_KEEP=14                           # days
MONTHLY_KEEP=400                        # days
COPY_TO=""                              # optional second copy, e.g. /mnt/nas/fireboard

# ---------- Prepare ----------
DAILY="$BACKUP_DIR/daily"
MONTHLY="$BACKUP_DIR/monthly"
LOG="$BACKUP_DIR/backup.log"
mkdir -p "$DAILY" "$MONTHLY" || exit 1
STAMP=$(date +%Y-%m-%d_%H%M)
MONTH=$(date +%Y-%m)
FILE="$DAILY/fireboard-$STAMP.dump"
TMP="$FILE.tmp"

log()  { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
fail() { rm -f "$TMP"; log "[FAILED] $*"; log "Backup FAILED - see the messages above."; exit 1; }

log "---------- Backup started $STAMP ----------"
cd "$APP_DIR" || fail "Folder not found: $APP_DIR"

# ---------- 1. Docker and database must be running ----------
docker info >/dev/null 2>&1 || fail "Docker is not running. Run: systemctl start docker"
[ -n "$(docker compose ps -q --status running db)" ] || fail "Database container is not running. Run: docker compose up -d"

# ---------- 2. Dump ----------
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TMP" \
    || fail "pg_dump failed."

# ---------- 3. Check the file ----------
docker compose exec -T db pg_restore --list < "$TMP" >/dev/null 2>&1 \
    || fail "Backup file is damaged - pg_restore cannot read it."
SIZE=$(stat -c %s "$TMP")
[ "$SIZE" -gt 1000 ] || fail "Backup file too small - $SIZE bytes"
mv "$TMP" "$FILE" || fail "Could not save $FILE"
log "[OK] $FILE - $SIZE bytes"

# ---------- 4. Monthly copy ----------
if [ ! -f "$MONTHLY/fireboard-$MONTH.dump" ]; then
    if cp "$FILE" "$MONTHLY/fireboard-$MONTH.dump"; then
        log "Monthly copy saved: fireboard-$MONTH.dump"
    else
        log "[WARNING] Could not save the monthly copy"
    fi
fi

# ---------- 5. Optional second copy ----------
if [ -n "$COPY_TO" ]; then
    if cp "$FILE" "$COPY_TO/"; then
        log "Copied to $COPY_TO"
    else
        log "[WARNING] Could not copy to $COPY_TO - the backup itself is OK"
    fi
fi

# ---------- 6. Remove old backups ----------
find "$DAILY" -name 'fireboard-*.dump' -mtime +"$DAILY_KEEP" -delete
find "$MONTHLY" -name 'fireboard-*.dump' -mtime +"$MONTHLY_KEEP" -delete

log "Done."
exit 0
