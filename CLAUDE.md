# MOTIE Workflow Platform

## What this is

A workflow and policy platform for The Gambia's Ministry of Trade, Industry, Regional Integration and Employment (MOTIE).
Applicants submit online; files move through the Ministry's chain of command (Records → Minister, or PS when the Minister is away → Directorate → officer), with delegation, deadlines, status tracking and a full audit trail.
ETLS (ECOWAS Trade Liberalisation Scheme) applications and certificates of origin are module 1. Other Ministry processes will be added later as modules.

## Stack

- Backend: FastAPI (Python)
- Database: PostgreSQL with pgvector; migrations with Alembic
- Frontend: Next.js
- Deployment: Docker Compose on a Ministry server
- AI: behind one `llm` module, so the provider can change (cloud API or a local model)

## Architecture rules

- Shared core (identity, workflow engine, documents, audit, notifications, AI services, reporting) is built once; each process is a module on top of it.
- One Postgres schema per module (`core`, `etls`, ...). Modules never touch each other's tables.
- Workflows are data: steps, allowed status changes and approver rules live in tables, not hard-coded.
- Approvals attach to positions, not named people. Delegation covers absences.
- Every status change writes to the append-only audit log.
- AI only suggests. It never changes a file's status. Every suggestion is stored with whether the officer accepted, edited or ignored it.
- Integrations (ECOWAS ETLS portal, GRA, business registry) go through adapters in an integration layer.

## How to work

Build on your own. Don't stop to ask about routine decisions or leave code for me to write; make a sensible choice, note it in the learning doc, and keep going. Stop and ask only when:
- a choice is hard to undo (data model changes after real data exists, deleting anything, a new paid service);
- a Ministry business rule is unclear (approval thresholds, who signs what, deadlines) — mark it `[CONFIRM]` in the code and the learning doc, use a reasonable placeholder, and keep going if you can;
- you'd add a framework or library beyond the stack above.

Quality bar for every step:
- Work in small steps: one table, endpoint, screen or feature at a time.
- Write tests for each step and run them; don't move on with failing tests.
- Prefer simple, readable code over clever code. Comment the *why*, not the *what*.
- Commit after each step with a clear message.
- Point out and fix security issues (auth, permissions, file uploads, injection) as you go.

## The learning doc: docs/LEARNING.md

I am a CS graduate, comfortable with FastAPI, Next.js and PostgreSQL, but new to AI engineering and to building a system this size. I will maintain this system and hand it over to the Ministry's ICT unit, so I need to understand everything you build.

After **every** step, update `docs/LEARNING.md` in the same commit. Follow the structure already in the file:

- **Build log** — add one entry per step, newest first: what you built, the files involved, and how to run and test it myself.
- **Concepts** — for each concept new to this project (e.g. migrations, JWT auth, state machines, background jobs, embeddings, chunking, hybrid search), add a short plain-language explanation, show *where* it appears in this codebase (file and function), and link one good free resource. Don't repeat a concept already explained; link to it instead.
- **Decisions** — every non-obvious choice: what you chose, the alternatives, and why. Include the decisions you made without asking me.
- **Open questions** — every `[CONFIRM]` item and anything I should check with the Ministry.
- **Check yourself** — two or three questions per step that I should be able to answer about the code. Put answers under a "Show answers" heading below them.

Write for me, not for a reviewer: plain words, short paragraphs, real file paths. Keep the doc tidy: update existing sections rather than appending duplicates.

## Commands

(Fill in as the project grows.)

- Start services: `docker compose up`
- Run the API: `uvicorn app.main:app --reload`
- Run migrations: `docker compose run --rm tools alembic upgrade head` (runs as `motie_owner`)
- Run tests: `docker compose run --rm tools pytest -v`
- Database users: `motie_app` (the API), `motie_owner` (migrations), `motie` superuser (setup only). Created by `db/init/10-db-users.sh`; rerun it with `docker compose exec db bash /docker-entrypoint-initdb.d/10-db-users.sh` after changing a password in `.env`.
- Postgres from the host: `localhost:5433` (5432 is taken by a local Windows Postgres)