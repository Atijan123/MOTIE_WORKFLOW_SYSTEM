#!/usr/bin/env bash
# Put a backup back on the office server (step 13d). This REPLACES the whole
# database and every uploaded file with the backup's.
#
#   scripts/restore.sh /mnt/motie-backup/daily/2026-11-26_0200
#   scripts/restore.sh /media/usb/motie-2026-11-23_0200.tar.age --key /media/key/offsite.key
#
#   --key FILE   the off-site PRIVATE key, for an encrypted weekly archive
#   --yes        don't ask (for scripts; CI uses it)
#
# What it does:
#   1. checks the backup can be read (checksums) before touching anything;
#   2. stops the staff app and the API, so nothing writes meanwhile;
#   3. empties the database and recreates the database users;
#   4. restores the database and the documents (office/backup/restore-inside.sh);
#   5. starts the app again and waits for its health check.
# Run it in the folder with docker-compose.office.yml and the server's .env.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

compose() { docker compose -f docker-compose.office.yml "$@"; }
env_value() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d "\r\"' "; }
# Docker on Windows (Git Bash) wants C:/... paths for mounts.
host_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }

source="" key="" yes=""
while [ $# -gt 0 ]; do
    case "$1" in
        --key) key="${2:?--key needs a file}"; shift 2 ;;
        --yes) yes=1; shift ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) source="$1"; shift ;;
    esac
done
[ -n "$source" ] || { echo "Usage: scripts/restore.sh <backup folder or .tar.age> [--key FILE] [--yes]" >&2; exit 1; }
[ -e "$source" ] || { echo "No such backup: $source" >&2; exit 1; }
[ -f .env ] || { echo "No .env here: run this in the server's motie folder." >&2; exit 1; }
if [[ "$source" == *.tar.age ]] && [ -z "$key" ]; then
    echo "An encrypted archive needs the off-site private key: --key /path/to/offsite.key" >&2; exit 1
fi

db="$(env_value POSTGRES_DB)"; superuser="$(env_value POSTGRES_USER)"
source_dir="$(cd "$(dirname "$source")" && pwd)"; source_name="$(basename "$source")"
mounts=(-v "$(host_path "$source_dir"):/restore:ro")
if [ -n "$key" ]; then
    key_dir="$(cd "$(dirname "$key")" && pwd)"
    mounts+=(-v "$(host_path "$key_dir/$(basename "$key")"):/keys/restore.key:ro")
fi

echo "This REPLACES the database '$db' and every uploaded document with: $source_name"
if [ -z "$yes" ]; then
    read -r -p "Type 'restore' to continue: " answer
    [ "$answer" = "restore" ] || { echo "Nothing changed."; exit 1; }
fi

echo "==> Checking the backup (nothing is changed yet)"
# A damaged or wrongly decrypted backup stops here, while the server still
# has its own data.
compose up -d --wait db
compose --profile tools run --rm "${mounts[@]}" backup restore-inside.sh --check "/restore/$source_name"

echo "==> Stopping the staff app and the API"
compose stop staff api

echo "==> Emptying the database"
compose up -d --wait db
compose exec -T db psql -v ON_ERROR_STOP=1 -U "$superuser" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$db\""
compose exec -T db bash /docker-entrypoint-initdb.d/10-db-users.sh

echo "==> Restoring"
compose --profile tools run --rm "${mounts[@]}" backup restore-inside.sh "/restore/$source_name"

echo "==> Starting the app"
compose up -d --wait api
compose up -d staff caddy
echo "Restored from $source_name. Sign in and check the latest cases look right."
