#!/usr/bin/env bash
# Wipe the DEVELOPMENT database and documents volume, then migrate and seed.
#
#     scripts/reset-dev.sh          asks you to type "reset" first
#     scripts/reset-dev.sh --yes    doesn't ask (for when you're sure)
#
# With imported historical letters in the database, --yes refuses unless
# --discard-history is given too: an import is lost without a trace (its audit
# row goes with the database), and only the register can bring it back.
#
# What it does:
#   1. stops the API, so nothing is using the database or the volume;
#   2. drops and recreates the database named POSTGRES_DB in .env;
#   3. re-runs db/init/10-db-users.sh (the database users and ownership);
#   4. deletes the "documents" volume (uploads and issued letters);
#   5. runs the migrations, then app/dev_seed.py (one user per post);
#   6. starts the API again, which creates an empty documents volume.
#
# It only runs when .env says APP_ENV=development. Never point it at a shared
# or production database: there is no undo. The test database (motie_test) is
# not touched; the test suite rebuilds that itself.
set -euo pipefail

# Git Bash on Windows rewrites arguments that look like paths
# (/docker-entrypoint-initdb.d/...) into Windows paths. Switch that off.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."

# Read one KEY=value from .env (no quotes, no spaces, no Windows line ending).
env_value() {
    grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d "\r\"' "
}

if [ ! -f .env ]; then
    echo "No .env here. Copy .env.example to .env first." >&2
    exit 1
fi

app_env="$(env_value APP_ENV || true)"
if [ "$app_env" != "development" ]; then
    echo "Refusing: APP_ENV in .env is '${app_env:-not set}', not 'development'." >&2
    echo "This script deletes the whole database. Run it on a development machine only." >&2
    exit 1
fi

db="$(env_value POSTGRES_DB)"
superuser="$(env_value POSTGRES_USER)"
project="$(docker compose config | sed -n 's/^name: //p' | head -n 1)"
if [ -z "$db" ] || [ -z "$superuser" ] || [ -z "$project" ]; then
    echo "Couldn't read POSTGRES_DB, POSTGRES_USER or the Compose project name." >&2
    exit 1
fi

yes=""
discard_history=""
for arg in "$@"; do
    case "$arg" in
        --yes) yes=1 ;;
        --discard-history) discard_history=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

docker compose up --detach --wait db
# 0 if the database or the table doesn't exist yet.
imported="$(docker compose exec -T db psql -U "$superuser" -d "$db" -Atc \
    "SELECT count(*) FROM etls.historical_letters" 2>/dev/null | tr -d "\r" || true)"
imported="${imported:-0}"

echo "This deletes, in Compose project '$project':"
echo "  - the database '$db' (every case, user and audit row)"
echo "  - the documents volume (every upload and issued letter)"
if [ "$imported" != "0" ]; then
    echo "  - $imported imported historical letters (re-run scripts/import-history.sh to get them back)"
    if [ -n "$yes" ] && [ -z "$discard_history" ]; then
        echo "Refusing: --yes won't discard imported letters. Add --discard-history if you mean to." >&2
        exit 1
    fi
fi
if [ -z "$yes" ]; then
    read -r -p "Type 'reset' to continue: " answer
    if [ "$answer" != "reset" ]; then
        echo "Nothing changed."
        exit 1
    fi
fi

echo "==> Stopping the API"
docker compose rm --stop --force api

echo "==> Recreating database '$db'"
docker compose up --detach --wait db
# Separate -c's run as separate statements: DROP DATABASE can't run inside a
# transaction. WITH (FORCE) closes any connection still open (e.g. a DB tool).
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$superuser" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$db\""
docker compose exec -T db bash /docker-entrypoint-initdb.d/10-db-users.sh

echo "==> Deleting the documents volume"
volume="$(docker volume ls --quiet \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.volume=documents")"
if [ -n "$volume" ]; then
    docker volume rm "$volume"
fi

echo "==> Migrating"
docker compose run --rm tools alembic upgrade head

echo "==> Seeding"
docker compose run --rm tools python -m app.dev_seed

echo "==> Starting the API"
docker compose up --detach api

echo "Done. The dev database and documents volume are fresh."
