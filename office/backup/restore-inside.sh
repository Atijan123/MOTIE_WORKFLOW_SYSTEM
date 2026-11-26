#!/usr/bin/env bash
# Restore one backup (step 13d), inside the "backup" container. Don't run it
# yourself: scripts/restore.sh stops the app, empties the database, then
# calls this, then starts the app again.
#
#   restore-inside.sh /restore/<date_time>            a daily backup folder
#   restore-inside.sh /restore/motie-<date>.tar.age   a weekly encrypted archive
#                                                     (needs the private key at /keys/restore.key)
#   restore-inside.sh --check <either>                only decrypt and check the
#                                                     checksums; change nothing
set -euo pipefail

: "${POSTGRES_DB:?}" "${MIGRATION_DB_PASSWORD:?}"
check_only=""
if [ "${1:-}" = "--check" ]; then check_only=1; shift; fi
source="${1:?which backup?}"
log() { echo "$(date '+%H:%M:%S') $*"; }
fail() { echo "RESTORE FAILED: $*" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [[ "$source" == *.tar.age ]]; then
    [ -f /keys/restore.key ] || fail "an encrypted archive needs the off-site private key (scripts/restore.sh --key)."
    log "Decrypting $(basename "$source")"
    age --decrypt --identity /keys/restore.key "$source" | tar --extract --directory "$work"
    folder="$(find "$work" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
else
    folder="$source"
fi
[ -f "$folder/SHA256SUMS" ] || fail "$folder isn't a backup (no SHA256SUMS)."

log "Checking the backup's checksums"
(cd "$folder" && sha256sum --check --quiet SHA256SUMS) || fail "the checksums don't match: this backup is damaged. Try an older one."
sed 's/^/  /' "$folder/backup.txt"
if [ -n "$check_only" ]; then
    log "The backup can be read and is complete."
    exit 0
fi

log "Restoring the database $POSTGRES_DB"
# Into the empty database scripts/restore.sh just made, as the schema owner,
# so every table is owned by motie_owner again. The dump's GRANTs give the
# API's user (motie_app) back exactly the rights it had.
PGPASSWORD="$MIGRATION_DB_PASSWORD" pg_restore --host db --username motie_owner --dbname "$POSTGRES_DB" \
    --no-owner --exit-on-error "$folder/database.dump"

log "Restoring the uploaded documents"
find /documents -mindepth 1 -delete
tar --extract --gzip --file "$folder/documents.tar.gz" --directory /documents
log "Restored: $(find /documents -type f | wc -l) files"
