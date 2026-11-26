#!/usr/bin/env bash
# The nightly backup (step 13d), inside the "backup" container:
#
#   docker compose -f docker-compose.office.yml run --rm backup
#
# (cron runs that at 02:00; docs/OFFICE-SETUP.md). It writes, on the USB drive
# mounted at /backups:
#
#   daily/<date_time>/database.dump    pg_dump, custom format (pg_restore reads it)
#   daily/<date_time>/documents.tar.gz every uploaded file and issued letter
#   daily/<date_time>/SHA256SUMS       checksums, checked before any restore
#   daily/<date_time>/backup.txt       when, what version, how big
#   last-success                       the time of the last good backup (the
#                                      staff home page warns when it's old)
#   offsite/motie-<date>.tar.age       once a week: the newest backup, encrypted
#                                      with the off-site PUBLIC key; copy it to
#                                      a second drive kept elsewhere
#
# Daily backups older than 30 days, and weekly archives older than 8 weeks,
# are deleted. A backup is written under a temporary name and renamed only
# once complete, so a half-finished one never counts.
set -euo pipefail

: "${POSTGRES_DB:?}" "${MIGRATION_DB_PASSWORD:?}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
KEEP_WEEKLY_DAYS="${BACKUP_KEEP_WEEKLY_DAYS:-56}"
ROOT=/backups

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { log "BACKUP FAILED: $*" >&2; exit 1; }

# The USB drive must really be there. Without this check, an unplugged drive
# leaves an empty folder, and backups would quietly fill the server's own disk.
[ -f "$ROOT/.motie-backup-drive" ] || fail "no backup drive at $ROOT (the file .motie-backup-drive is missing). Is the USB drive plugged in and mounted?"
touch "$ROOT/.write-test" 2>/dev/null && rm -f "$ROOT/.write-test" || fail "can't write to the backup drive at $ROOT."

# To the second: two backups in one minute (e.g. one by hand, then an update's)
# must not share a name.
stamp="$(date +%Y-%m-%d_%H%M%S)"
final="$ROOT/daily/$stamp"
partial="$ROOT/daily/.partial-$stamp"
mkdir -p "$ROOT/daily" "$ROOT/offsite"
rm -rf "$ROOT"/daily/.partial-*  # an earlier run that didn't finish
mkdir "$partial"

log "Backing up the database $POSTGRES_DB"
# As the schema owner, who owns every table. Custom format: compressed, and
# pg_restore can restore it table by table if ever needed.
PGPASSWORD="$MIGRATION_DB_PASSWORD" pg_dump --host db --username motie_owner --dbname "$POSTGRES_DB" \
    --format custom --file "$partial/database.dump"

log "Backing up the uploaded documents"
tar --create --gzip --file "$partial/documents.tar.gz" --directory /documents .

{
    echo "created: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "version: ${MOTIE_VERSION:-unknown}"
    echo "database: $(du -h "$partial/database.dump" | cut -f1)"
    echo "documents: $(du -h "$partial/documents.tar.gz" | cut -f1)"
} > "$partial/backup.txt"
(cd "$partial" && sha256sum database.dump documents.tar.gz backup.txt > SHA256SUMS)

[ ! -e "$final" ] || fail "$final already exists."
# -T: rename the folder itself; never move it *into* an existing one.
mv -T "$partial" "$final"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$ROOT/last-success.tmp" && mv "$ROOT/last-success.tmp" "$ROOT/last-success"
log "Backup done: $final"

# Once a week (or when there is none yet): the newest backup, encrypted for
# off-site keeping. Only the PUBLIC key is on the server: whoever steals the
# server or this drive can't read the archive.
if [ -f /keys/offsite.pub ]; then
    newest_weekly="$(find "$ROOT/offsite" -maxdepth 1 -name 'motie-*.tar.age' -mtime -7 | head -n 1)"
    if [ -z "$newest_weekly" ] || [ "${BACKUP_FORCE_WEEKLY:-}" = "1" ]; then
        archive="$ROOT/offsite/motie-$stamp.tar.age"
        log "Weekly encrypted archive: $archive"
        tar --create --directory "$ROOT/daily" "$stamp" | age --encrypt --recipients-file /keys/offsite.pub > "$archive.partial"
        mv "$archive.partial" "$archive"
    fi
else
    log "No off-site public key (/keys/offsite.pub): no weekly encrypted archive. See docs/OFFICE-SETUP.md."
fi

log "Removing daily backups older than $KEEP_DAYS days and weekly archives older than $KEEP_WEEKLY_DAYS days"
find "$ROOT/daily" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
find "$ROOT/offsite" -maxdepth 1 -name 'motie-*.tar.age' -mtime +"$KEEP_WEEKLY_DAYS" -delete
log "Free space on the backup drive: $(df -h "$ROOT" | awk 'NR==2 {print $4}')"
