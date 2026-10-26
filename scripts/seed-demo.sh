#!/usr/bin/env bash
# Reset the DEVELOPMENT database, then fill it with fictional facility letter
# cases for a demo, one at each stage, and print the logins.
#
#     scripts/seed-demo.sh          asks you to type "reset" first
#     scripts/seed-demo.sh --yes    doesn't ask
#
# Everything it creates is made up (backend/app/demo_seed.py). It only runs
# when .env says APP_ENV=development, and the reset it starts with deletes
# every case, user and upload in the dev database: there is no undo.
set -euo pipefail
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."

app_env="$(grep -E '^APP_ENV=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\r\"' " || true)"
if [ "$app_env" != "development" ]; then
    echo "Refusing: APP_ENV in .env is '${app_env:-not set}', not 'development'." >&2
    echo "The demo seed starts by deleting the whole database. Development machines only." >&2
    exit 1
fi

# The same reset as always (it checks APP_ENV again, and asks unless --yes).
bash scripts/reset-dev.sh "$@"

echo "==> Creating the demo cases"
docker compose run --rm tools python -m app.demo_seed
