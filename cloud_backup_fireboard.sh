#!/bin/bash
# ============================================================
#  Fire Board Estimator - encrypted copy of the backups to Google Drive (rclone)
#
#  backup_fireboard.sh makes the local backups (C:\fireboard_backup\daily, monthly).
#  This script uploads them to Google Drive, ENCRYPTED by rclone ("crypt" remote):
#  on Google Drive the names and contents are unreadable without your password.
#
#  One-time setup: see README_cloud_backup.txt (install rclone, create the
#  remotes "gdrive" and "gdrive-crypt" as root).
#
#  Usage (as root):
#    sudo /opt/fireboard/cloud_backup_fireboard.sh          upload new backups, remove old ones
#    sudo /opt/fireboard/cloud_backup_fireboard.sh list     list what is on Google Drive (decrypted names)
#    sudo /opt/fireboard/cloud_backup_fireboard.sh test     download the newest one and check it can be restored
#  Cron (every hour, 10 minutes after the local backup):
#    15 * * * * /opt/fireboard/cloud_backup_fireboard.sh
#
#  Results are written to the same backup.log as backup_fireboard.sh.
# ============================================================
set -u

# ---------- Settings ----------
APP_DIR=/opt/fireboard
BACKUP_DIR=/mnt/c/fireboard_backup      # same as in backup_fireboard.sh
REMOTE=gdrive-crypt:fireboard            # encrypted remote + folder
CLOUD_DAILY_KEEP=30d                     # daily backups kept on Google Drive
CLOUD_MONTHLY_KEEP=400d                  # monthly backups kept on Google Drive
UPLOAD_MAX_AGE=7d                        # only upload local backups newer than this

LOG="$BACKUP_DIR/backup.log"
LOCK=/tmp/fireboard_cloud_backup.lock

log()  { echo "$(date '+%Y-%m-%d %H:%M:%S') [cloud] $*" | tee -a "$LOG"; }
fail() { log "[FAILED] $*"; exit 1; }

[ "$(id -u)" = "0" ] || { echo "Please run with sudo."; exit 1; }
command -v rclone >/dev/null 2>&1 || fail "rclone is not installed - see README_cloud_backup.txt"
rclone listremotes 2>/dev/null | grep -qx "${REMOTE%%:*}:" \
    || fail "rclone remote '${REMOTE%%:*}' not found - see README_cloud_backup.txt"

# only one copy at a time (cron + manual run)
exec 9>"$LOCK"
flock -n 9 || { echo "Another cloud backup is running."; exit 0; }

ACTION="${1:-upload}"

# ---------- list ----------
if [ "$ACTION" = "list" ]; then
    echo "== $REMOTE/daily"
    rclone lsl "$REMOTE/daily" | sort -k2,3 | tail -20
    echo "== $REMOTE/monthly"
    rclone lsl "$REMOTE/monthly" | sort -k2,3
    exit 0
fi

# ---------- test: download the newest backup and check it ----------
if [ "$ACTION" = "test" ]; then
    NEWEST=$(rclone lsf "$REMOTE/daily" --files-only | sort | tail -1)
    [ -n "$NEWEST" ] || fail "No backups on Google Drive yet."
    TMP=$(mktemp -d)
    rclone copy "$REMOTE/daily/$NEWEST" "$TMP/" || fail "Download failed: $NEWEST"
    cd "$APP_DIR" || fail "Folder not found: $APP_DIR"
    if docker compose exec -T db pg_restore --list < "$TMP/$NEWEST" >/dev/null 2>&1; then
        log "[OK] Test restore check passed: $NEWEST ($(stat -c %s "$TMP/$NEWEST") bytes, decrypted)"
        rm -rf "$TMP"; exit 0
    fi
    rm -rf "$TMP"
    fail "Downloaded $NEWEST but pg_restore cannot read it."
fi

[ "$ACTION" = "upload" ] || { echo "Unknown action: $ACTION (use: upload, list, test)"; exit 1; }

# ---------- upload ----------
log "---------- Cloud upload started ----------"
for SUB in daily monthly; do
    [ -d "$BACKUP_DIR/$SUB" ] || continue
    AGE=()
    [ "$SUB" = "daily" ] && AGE=(--max-age "$UPLOAD_MAX_AGE")   # monthly: upload all
    # copy = only files not already on Google Drive; local files are never deleted
    rclone copy "$BACKUP_DIR/$SUB" "$REMOTE/$SUB" \
        --include 'fireboard-*.dump' "${AGE[@]}" \
        --retries 3 --low-level-retries 10 2>>"$LOG" \
        || fail "Upload of $SUB failed (no internet? Google login expired?) - local backups are OK"
done
COUNT=$(rclone lsf "$REMOTE/daily" --files-only 2>/dev/null | wc -l)
log "[OK] Uploaded. Google Drive now has $COUNT daily backup(s)."

# ---------- remove old backups on Google Drive ----------
rclone delete "$REMOTE/daily"   --min-age "$CLOUD_DAILY_KEEP"   --include 'fireboard-*.dump' 2>>"$LOG" \
    || log "[WARNING] Could not remove old daily backups on Google Drive"
rclone delete "$REMOTE/monthly" --min-age "$CLOUD_MONTHLY_KEEP" --include 'fireboard-*.dump' 2>>"$LOG" \
    || log "[WARNING] Could not remove old monthly backups on Google Drive"
log "Done."
exit 0
