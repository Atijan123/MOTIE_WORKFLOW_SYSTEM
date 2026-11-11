# MOTIE Workflow Platform

[![CI](https://github.com/Atijan123/MOTIE_WORKFLOW_SYSTEM/actions/workflows/ci.yml/badge.svg)](https://github.com/Atijan123/MOTIE_WORKFLOW_SYSTEM/actions/workflows/ci.yml)

A workflow and policy platform for The Gambia's Ministry of Trade, Industry,
Regional Integration and Employment (MOTIE). Applicants apply online; files
move through the Ministry's chain of command with delegation, deadlines,
status tracking and a full audit trail. ETLS facility letters are the first
module.

- Backend: FastAPI + PostgreSQL (pgvector), migrations with Alembic (`backend/`)
- Frontend: Next.js (`frontend/`), browser walk-throughs with Playwright (`frontend/e2e/`)
- Everything runs in Docker Compose (`docker-compose.yml`)

## Getting started

```sh
cp .env.example .env      # then fill in every password and JWT_SECRET
docker compose up -d
docker compose run --rm tools alembic upgrade head
bash scripts/seed-demo.sh # development only: fictional demo data and logins
```

The commands for tests, seeding and imports are in [CLAUDE.md](CLAUDE.md#commands).

## Documentation

- [docs/LEARNING.md](docs/LEARNING.md): build log, concepts, decisions and open questions
- [docs/SCREENS.md](docs/SCREENS.md): the screens and their rules

Every push runs [CI](.github/workflows/ci.yml): backend tests, frontend
typecheck and unit tests, and all Playwright walk-throughs on a fresh demo
database.
