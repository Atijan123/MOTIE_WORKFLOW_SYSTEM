#!/usr/bin/env bash
# CI only (.github/workflows/ci.yml): a throwaway .env with random passwords,
# and docker-compose.ci.yml as the Compose override, for project "motie-ci".
# Refuses to run outside CI, so it can't replace your own .env by accident.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
    echo "Refusing: this prepares a CI run (it replaces .env). Run it only in GitHub Actions." >&2
    exit 1
fi

random() { openssl rand -hex 24 2>/dev/null || python -c "import secrets; print(secrets.token_hex(24))"; }

{
    echo "POSTGRES_USER=motie"
    echo "POSTGRES_PASSWORD=$(random)"
    echo "POSTGRES_DB=motie"
    echo "MIGRATION_DB_PASSWORD=$(random)"
    echo "APP_DB_PASSWORD=$(random)"
    echo "JWT_SECRET=$(random)$(random)"
    # Development: the demo seed may run, and the published dev keys work.
    echo "APP_ENV=development"
} > .env
cp docker-compose.ci.yml docker-compose.override.yml
echo "CI stack ready: project ${COMPOSE_PROJECT_NAME:-?}, docker-compose.ci.yml as the override."
