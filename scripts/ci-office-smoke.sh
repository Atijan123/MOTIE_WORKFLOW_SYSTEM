#!/usr/bin/env bash
# CI only (step 13c): start the office stack (docker-compose.office.yml) with
# throwaway settings and check it over real HTTPS, through Caddy and its
# internal certificate authority, as a staff PC would see it.
#
#   - the API's health check answers through Caddy, with a certificate the
#     downloaded root certificate vouches for;
#   - the staff app's login page loads;
#   - http:// is sent to https://;
#   - nothing of the API but /api/health is reachable from the network.
#
# It runs as its own Compose project and removes everything afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
    echo "Refusing: this replaces .env. It runs only in GitHub Actions." >&2
    exit 1
fi

export COMPOSE_PROJECT_NAME=motie-office-ci
compose() { docker compose -f docker-compose.office.yml "$@"; }
random() { openssl rand -hex 24; }
HOST=etls.test
WORK="$(mktemp -d)"

cleanup() {
    compose --profile tools down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1 || true
    rm -f .env
    rm -rf "$WORK"
}
trap cleanup EXIT

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
    echo "MOTIE_VERSION=ci"
} > .env

echo "==> Building and starting the office stack"
compose build
compose up -d --wait db
compose --profile tools run --rm tools alembic upgrade head
compose up -d --wait api
compose up -d staff caddy

curl_office() {
    curl --silent --show-error --resolve "$HOST:443:127.0.0.1" --resolve "$HOST:80:127.0.0.1" "$@"
}

echo "==> Waiting for Caddy's certificate authority"
for _ in $(seq 1 30); do
    if compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$WORK/root.crt" >/dev/null 2>&1; then break; fi
    # The first https request makes Caddy issue its certificates.
    curl_office --insecure --output /dev/null "https://$HOST/api/health" || true
    sleep 2
done
test -s "$WORK/root.crt" || { echo "Caddy's root certificate never appeared." >&2; exit 1; }

check() {  # check <what> <expected> <actual>
    if [ "$2" = "$3" ]; then echo "  ok: $1"; else echo "  FAILED: $1 (expected $2, got $3)" >&2; exit 1; fi
}

echo "==> Checking it over https, trusting only Caddy's root certificate"
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

echo "The office stack works over https."
