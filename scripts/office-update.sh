#!/usr/bin/env bash
# Update the office server to a new version (step 13f), safely:
#
#   sudo bash scripts/office-update.sh                 the newest version on GitHub (origin/main)
#   sudo bash scripts/office-update.sh --ref v1.4.0    a given tag or commit
#   sudo bash scripts/office-update.sh --from /media/usb/motie-update-v1.4.0
#                                                      offline: from a USB stick made by
#                                                      scripts/office-bundle.sh on a connected PC
#
# What it does:
#   1. a backup, now (the nightly one, run early); its folder is the way back;
#   2. gets the new version's code (git), and its images (built here, or
#      loaded from the USB stick), tagged with the new version: the current
#      version's images stay, to go back to;
#   3. runs the database migrations;
#   4. starts the new version and checks its health over https;
#   5. if anything in 2-4 fails: ROLLS BACK to the old code and images, and
#      restores the database from step 1's backup (the migrations may have
#      changed it), then checks health again.
# Run it in the server's motie folder (with .env and docker-compose.office.yml).
set -Eeuo pipefail  # -E: the rollback trap also fires inside functions
cd "$(dirname "$0")/.."

compose() { docker compose -f docker-compose.office.yml "$@"; }
env_value() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d "\r\"' "; }
set_env() {  # set_env KEY value: change one line of .env
    if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}
log() { echo "$(date '+%H:%M:%S') ==> $*"; }

ref="origin/main" from="" fetch=1
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) ref="${2:?--ref needs a tag or commit}"; shift 2 ;;
        --from) from="${2:?--from needs the update folder}"; shift 2 ;;
        --no-fetch) fetch=""; shift ;;  # the code is already here (CI)
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done
[ -f .env ] || { echo "No .env here: run this in the server's motie folder." >&2; exit 1; }
[ "$(env_value APP_ENV)" != "development" ] || { echo "Refusing: this is for the office server." >&2; exit 1; }

old_commit="$(git rev-parse HEAD)"
old_version="$(env_value MOTIE_VERSION)"
old_version="${old_version:-local}"
backup_root="$(env_value BACKUP_PATH)"
host="$(env_value OFFICE_HOSTNAME)"
bind_ip="$(env_value OFFICE_BIND_IP)"

health() {
    # The server checking itself, through Caddy, as staff would reach it.
    # (-k: the server needn't trust its own certificate authority for this.)
    local code
    for _ in $(seq 1 30); do
        code="$(curl -sk --resolve "$host:443:$bind_ip" -o /dev/null -w '%{http_code}' "https://$host/api/health/db" || true)"
        if [ "$code" = "200" ] && curl -skf --resolve "$host:443:$bind_ip" -o /dev/null "https://$host/login"; then
            return 0
        fi
        sleep 3
    done
    return 1
}

start_version() {  # start_version <version>: migrate, start, check
    set_env MOTIE_VERSION "$1"
    compose up -d --wait db
    compose --profile tools run --rm tools alembic upgrade head
    [ "${OFFICE_UPDATE_SIMULATE_FAILURE:-}" = "after-migrate" ] && { echo "(simulated failure, for the CI test)" >&2; return 1; }
    compose up -d --wait api
    compose up -d staff caddy
    health
}

# 1. Backup first.
log "Backing up before the update"
compose --profile tools run --rm backup
backup_dir="$(ls -1d "$backup_root"/daily/20* | sort | tail -n 1)"
log "The way back: $backup_dir"

rollback() {
    log "UPDATE FAILED: rolling back to $old_version ($old_commit)"
    git checkout --quiet --force "$old_commit"
    set_env MOTIE_VERSION "$old_version"
    bash scripts/restore.sh "$backup_dir" --yes
    if health; then
        log "Rolled back. The server runs $old_version again, with the data from just before the update."
    else
        log "ROLLBACK DID NOT COME UP HEALTHY. See docs/OFFICE-SETUP.md, 'If an update fails'."
    fi
    exit 1
}
trap rollback ERR

# 2. The new version's code and images.
if [ -n "$from" ]; then
    log "Loading the update from $from"
    git fetch --quiet "$from/code.bundle" "+refs/tags/*:refs/tags/*" "+refs/heads/*:refs/remotes/bundle/*"
    new_commit="$(cat "$from/COMMIT")"
    git checkout --quiet --force "$new_commit"
    new_version="$(cat "$from/VERSION")"
    for image in "$from"/images/*.tar; do docker load --input "$image"; done
else
    if [ -n "$fetch" ]; then
        log "Fetching from GitHub"
        git fetch --quiet --tags origin
    fi
    git checkout --quiet --force "$(git rev-parse "$ref^{commit}")"
    new_version="$(git describe --tags --always)"
    log "Building $new_version"
    MOTIE_VERSION="$new_version" compose --profile tools build
fi

# 3-4. Migrate, start, check.
log "Starting $new_version (was $old_version)"
start_version "$new_version"
trap - ERR
log "Updated to $new_version. Old images ($old_version) are kept until the next update."
# Images two versions back are no longer needed.
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^motie/office-' \
    | grep -v -e ":$new_version\$" -e ":$old_version\$" | xargs -r docker image rm >/dev/null 2>&1 || true
