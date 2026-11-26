#!/usr/bin/env bash
# CI only (steps 13c, 13d): the office stack (docker-compose.office.yml) with
# throwaway settings.
#
# 13c: checked over real HTTPS, through Caddy and its internal certificate
#      authority, as a staff PC would see it: the API's health check, the
#      staff login page, http -> https, HSTS, and only /api/health of the API.
# 13d: a backup and a restore, the way they'd happen after a disaster: real
#      data, the nightly backup onto a "USB drive", the weekly encrypted
#      archive, then every volume destroyed, then scripts/restore.sh from the
#      ENCRYPTED archive with the off-site private key; the data must be back.
#
# It runs as its own Compose project and removes everything afterwards.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
    echo "Refusing: this replaces .env. It runs only in GitHub Actions." >&2
    exit 1
fi

export COMPOSE_PROJECT_NAME=motie-office-ci
compose() { docker compose -f docker-compose.office.yml "$@"; }
random() { openssl rand -hex 24; }
# Docker on Windows (Git Bash) wants C:/... paths for mounts.
host_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
HOST=etls.test
WORK="$PWD/.ci-office"  # inside the checkout: Docker can mount it on Windows too

cleanup() {
    compose --profile tools down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1 || true
    rm -f .env
    rm -rf "$WORK"
}
trap cleanup EXIT
rm -rf "$WORK"
mkdir -p "$WORK/usb" "$WORK/keys" "$WORK/safe"

# Throwaway settings. The office network is Docker's own range, because the
# checks below come from this machine through Docker's port forwarding.
{
    echo "OFFICE_HOSTNAME=$HOST"
    echo "OFFICE_BIND_IP=127.0.0.1"
    echo "OFFICE_NETWORK=172.16.0.0/12"
    echo "POSTGRES_USER=motie"
    echo "POSTGRES_PASSWORD=$(random)"
    echo "POSTGRES_DB=motie"
    echo "MIGRATION_DB_PASSWORD=$(random)"
    echo "APP_DB_PASSWORD=$(random)"
    echo "JWT_SECRET=$(random)$(random)"
    echo "MFA_SECRET_KEY=$(random)$(random)"
    echo "STAFF_PORTAL_KEY=$(random)$(random)"
    echo "FACILITY_LETTER_REFERENCE_FORMAT=TEST REF {year}"
    echo "BACKUP_PATH=$(host_path "$WORK/usb")"
    echo "OFFSITE_KEY_DIR=$(host_path "$WORK/keys")"
    echo "MOTIE_VERSION=ci"
} > .env

check() {  # check <what> <expected> <actual>
    if [ "$2" = "$3" ]; then echo "  ok: $1"; else echo "  FAILED: $1 (expected $2, got $3)" >&2; exit 1; fi
}

echo "==> Building and starting the office stack"
compose --profile tools build
compose up -d --wait db
compose --profile tools run --rm tools alembic upgrade head
compose up -d --wait api
compose up -d staff caddy

# ---------------------------------------------------------------- 13c: https
curl_office() {
    curl --silent --show-error --resolve "$HOST:443:127.0.0.1" --resolve "$HOST:80:127.0.0.1" "$@"
}

echo "==> Waiting for Caddy's certificate authority"
for _ in $(seq 1 30); do
    if compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$(host_path "$WORK/root.crt")" >/dev/null 2>&1; then break; fi
    # The first https request makes Caddy issue its certificates.
    curl_office --insecure --output /dev/null "https://$HOST/api/health" || true
    sleep 2
done
test -s "$WORK/root.crt" || { echo "Caddy's root certificate never appeared." >&2; exit 1; }

echo "==> Checking it over https, trusting only Caddy's root certificate"
code=""
for _ in $(seq 1 30); do
    code="$(curl_office --cacert "$WORK/root.crt" --output /dev/null --write-out '%{http_code}' "https://$HOST/api/health/db" || true)"
    [ "$code" = "200" ] && break
    sleep 2
done
check "the API's health check, through Caddy, with a trusted certificate" 200 "$code"

login="$(curl_office --cacert "$WORK/root.crt" "https://$HOST/login")"
case "$login" in *"Staff log in"*) echo "  ok: the staff login page" ;; *) echo "  FAILED: the staff login page" >&2; exit 1 ;; esac

code="$(curl_office --output /dev/null --write-out '%{http_code}' "http://$HOST/login")"
check "http:// is redirected" 308 "$code"

code="$(curl_office --cacert "$WORK/root.crt" --output /dev/null --write-out '%{http_code}' "https://$HOST/api/auth/me")"
check "the API's other endpoints aren't reachable through Caddy" 404 "$code"

hsts="$(curl_office --cacert "$WORK/root.crt" --head "https://$HOST/login" | tr -d '\r' | grep -i '^strict-transport-security' || true)"
case "$hsts" in *max-age=31536000*) echo "  ok: browsers are told to use https only" ;; *) echo "  FAILED: no HSTS header" >&2; exit 1 ;; esac

# ---------------------------------------------------------- 13d: backup, restore
echo "==> Some real data: a staff account and an uploaded file"
compose --profile tools run --rm tools python -c "
import asyncio
from app.core.identity.service import create_user
from app.db.session import SessionLocal, engine
async def main():
    async with SessionLocal() as s:
        await create_user(s, email='restore-check@motie.test', full_name='Restore Check', password='a long test password', role_codes=['officer'])
    await engine.dispose()
asyncio.run(main())"
compose --profile tools run --rm --entrypoint sh backup -c "echo 'scan of an invoice' > /documents/restore-check.txt"

count_users() {
    compose exec -T db psql -U motie -d motie -Atc "SELECT count(*) FROM core.users WHERE email = 'restore-check@motie.test'" | tr -d '\r'
}
check "the account exists before the backup" 1 "$(count_users)"

echo "==> The off-site key pair: the public half for the server, the private half kept away"
compose --profile tools run --rm --entrypoint age-keygen backup 2>/dev/null > "$WORK/safe/offsite.key"
grep -o 'age1[0-9a-z]*' "$WORK/safe/offsite.key" > "$WORK/keys/offsite.pub"
test -s "$WORK/keys/offsite.pub"

echo "==> A backup with no USB drive refuses to run"
if compose --profile tools run --rm backup >/dev/null 2>&1; then
    echo "  FAILED: the backup ran without the .motie-backup-drive marker" >&2; exit 1
fi
echo "  ok: no marker, no backup"

echo "==> The nightly backup, onto the USB drive"
touch "$WORK/usb/.motie-backup-drive"
compose --profile tools run --rm backup
daily="$(find "$WORK/usb/daily" -mindepth 1 -maxdepth 1 -type d -name '20*' | head -n 1)"
test -n "$daily" && test -s "$daily/database.dump" && test -s "$daily/documents.tar.gz" && test -s "$daily/SHA256SUMS"
echo "  ok: $(basename "$daily") with its checksums"
test -s "$WORK/usb/last-success" && echo "  ok: last-success written"
archive="$(find "$WORK/usb/offsite" -name 'motie-*.tar.age' | head -n 1)"
test -s "$archive" && echo "  ok: the weekly encrypted archive"
# The archive can't be read as a plain tar: it's encrypted.
if tar -tf "$archive" >/dev/null 2>&1; then echo "  FAILED: the archive isn't encrypted" >&2; exit 1; fi
echo "  ok: the archive is unreadable without the key"

echo "==> Disaster: every volume destroyed (database, documents, certificates)"
compose --profile tools down --volumes --timeout 5
compose up -d --wait db   # an empty database, as on a new machine
compose --profile tools run --rm tools alembic upgrade head

echo "==> Restoring from the ENCRYPTED weekly archive, with the off-site private key"
bash scripts/restore.sh "$archive" --key "$WORK/safe/offsite.key" --yes

check "the account is back" 1 "$(count_users)"
file="$(compose --profile tools run --rm --entrypoint cat backup /documents/restore-check.txt | tr -d '\r')"
check "the uploaded file is back" "scan of an invoice" "$file"
code="$(compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health/db').status)" | tr -d '\r')"
check "the API is healthy after the restore" 200 "$code"

echo "==> A damaged backup is refused before anything is touched"
echo "tampered" >> "$daily/documents.tar.gz"
if bash scripts/restore.sh "$daily" --yes >/dev/null 2>&1; then
    echo "  FAILED: a damaged backup was restored" >&2; exit 1
fi
check "the data is still there after the refused restore" 1 "$(count_users)"

# ------------------------------------------------------------- 13f: updates
echo "==> An update that fails after its migrations is rolled back"
before="$(grep -E '^MOTIE_VERSION=' .env | cut -d= -f2)"
if OFFICE_UPDATE_SIMULATE_FAILURE=after-migrate bash scripts/office-update.sh --ref HEAD --no-fetch; then
    echo "  FAILED: the update reported success" >&2; exit 1
fi
check "the version is back to what it was" "$before" "$(grep -E '^MOTIE_VERSION=' .env | cut -d= -f2)"
check "the data survived the rollback" 1 "$(count_users)"
code="$(compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health/db').status)" | tr -d '\r')"
check "the API is healthy after the rollback" 200 "$code"

echo "==> A normal update"
bash scripts/office-update.sh --ref HEAD --no-fetch
check "it runs the version named after the commit" "$(git describe --tags --always)" "$(grep -E '^MOTIE_VERSION=' .env | cut -d= -f2)"
check "the data is still there" 1 "$(count_users)"

echo "The office stack works over https, its backups restore, and updates roll back on failure."
