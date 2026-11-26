#!/usr/bin/env bash
# CI only: after every job, remove what it made, because the runner's disk is
# small (your PC). Your own dev stack (project "motie_workflow_system") and its
# images are never touched: only project "motie-ci", dangling images, and
# build cache older than 7 days.
set -uo pipefail  # no -e: clean up as much as possible, whatever fails
cd "$(dirname "$0")/.."

if [ "${COMPOSE_PROJECT_NAME:-}" != "motie-ci" ]; then
    echo "Refusing: COMPOSE_PROJECT_NAME isn't motie-ci; this would remove another project's volumes." >&2
    exit 1
fi

docker compose --profile tools down --volumes --remove-orphans --timeout 5
docker image prune --force
docker builder prune --force --filter until=168h
# Playwright's local results (the failures are uploaded to GitHub first).
rm -rf frontend/e2e/test-results frontend/e2e/playwright-report
rm -f .env docker-compose.override.yml
echo "Cleaned up."
