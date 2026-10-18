# Learning doc — MOTIE Workflow Platform

Kept up to date by Claude Code after every build step. Read the newest build log entry, then work through its concepts and "Check yourself" questions.

## Contents

1. Build log
2. Concepts
3. Decisions
4. Open questions
5. Check yourself

---

## 1. Build log

Newest first. Each entry: what was built, the files involved, how to run and test it.

### Step 1 — FastAPI skeleton connected to Postgres (2026-10-18)
**Built:** two Docker Compose services: Postgres 16 (with pgvector available) and the FastAPI app. The app reads `DATABASE_URL`, keeps one connection pool, and exposes `/health` (the process is alive) and `/health/db` (Postgres answers a query). If the database is down, `/health/db` returns 503 with a plain message and logs the full error on the server. Tests run against a separate `motie_test` database.
**Files:** docker-compose.yml, .env.example, backend/Dockerfile, backend/requirements.txt, backend/requirements-dev.txt, backend/app/main.py, backend/app/core/config.py, backend/app/db/session.py, backend/app/api/health.py, backend/tests/conftest.py, backend/tests/test_health.py
**Try it:**
- `docker compose up --build`, then `curl localhost:8000/health` and `curl localhost:8000/health/db`.
- `docker compose exec api pytest -v` runs the tests inside the API container.
- `docker compose stop db`, then `curl -i localhost:8000/health/db` should give 503 with no hostnames or usernames in the body. Bring it back with `docker compose start db`.
- From your own machine, a database tool connects to `localhost:5433` (not 5432).
**New concepts:** Docker Compose networking, Connection pool, Liveness vs readiness, Lifespan and `yield` dependencies, Test database with rollback

## 2. Concepts

One short explanation per concept, where it lives in this codebase, and one free resource.

### Docker Compose networking
**What:** Compose puts all services on one private network and gives each one a hostname equal to its service name. Every container has its *own* `localhost`, so the API must reach Postgres as `db`, not `localhost`. `ports:` only matters for reaching a container from your own machine.
**Here:** docker-compose.yml: `DATABASE_URL` uses host `db`, and the db service publishes `127.0.0.1:5433:5432` (host port 5433 → container port 5432).
**Learn more:** [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/)

### Connection pool
**What:** opening a Postgres connection is slow (network handshake + login). A pool keeps a few connections open and lends them out to requests, then takes them back. SQLAlchemy's *engine* owns the pool; a *session* borrows a connection for the length of one request.
**Here:** backend/app/db/session.py: `engine` (one per process) and `get_session()` (one per request).
**Learn more:** [SQLAlchemy: Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)

### Liveness vs readiness
**What:** two different health questions. *Liveness*: is the process running? *Readiness*: can it actually do its job (here: reach the database)? Keeping them apart tells an operator *which* part is broken.
**Here:** backend/app/api/health.py: `health()` never touches the database, while `health_db()` runs `SELECT 1`.
**Learn more:** [Kubernetes: liveness and readiness probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/). The same idea applies outside Kubernetes.

### Lifespan and `yield` dependencies
**What:** in both, code before `yield` is setup and code after `yield` is cleanup. They differ in *how often* that happens. `lifespan` runs once for the whole server (startup and shutdown). A `yield` dependency runs once per request.
**Here:** backend/app/main.py `lifespan()` closes the pool on shutdown. backend/app/db/session.py `get_session()` closes each request's session.
**Learn more:** [FastAPI: Lifespan events](https://fastapi.tiangolo.com/advanced/events/), [FastAPI: Dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)

### Test database with rollback
**What:** tests use a separate database so they never damage dev data. Each test runs inside one big transaction that is rolled back at the end, so tests can't leave data behind for each other. Code under test can still call `commit()`: in tests that only commits a *savepoint* inside the outer transaction.
**Here:** backend/tests/conftest.py: `_create_test_database()`, `db_session` and `client` fixtures. The `client` fixture swaps the real `get_session` for the test one with `app.dependency_overrides`.
**Learn more:** [SQLAlchemy: Joining a Session into an External Transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)

## 3. Decisions

| Date | Decision | Alternatives considered | Why |
| --- | --- | --- | --- |
| 2026-10-18 | SQLAlchemy 2.0 async + asyncpg | raw asyncpg; SQLModel | Chosen by you. Widely used, works with Alembic, async fits FastAPI. |
| 2026-10-18 | API and db both in Compose; source bind-mounted with `--reload` | only Postgres in Docker | Chosen by you. One command starts everything; edits reload without rebuilding. |
| 2026-10-18 | `pgvector/pgvector:pg16` image | plain `postgres:16` and install pgvector later | The stack needs pgvector. This image has it ready; we enable it with a migration when AI work starts. |
| 2026-10-18 | Ports bound to 127.0.0.1 only | `5432:5432` (all interfaces) | An exposed Postgres port on a server is a common way in for attackers. |
| 2026-10-18 | Postgres published on host port 5433 | 5432 | A Postgres installed on your Windows machine already uses 5432. Containers are unaffected. |
| 2026-10-18 | `/health/db` returns 503 with a fixed body and logs the real error | 500; returning the error text | 503 means "temporarily unavailable", which is right for monitoring. The error text can leak the DB host and username. |
| 2026-10-18 | Test tools in `requirements-dev.txt`, chosen by a Docker build argument | one requirements file | Production images shouldn't carry test tools. |
| 2026-10-18 | Async tests use anyio's pytest plugin | pytest-asyncio | anyio already comes with FastAPI, so no extra library. |
| 2026-10-18 | Tests use httpx `AsyncClient` in-process | running a real server in tests | Faster, and the test and the app share one database transaction. |

## 4. Open questions

Items marked `[CONFIRM]` in the code, to check with the Ministry.

- [ ] (none yet)

## 5. Check yourself

Questions per step. Try to answer before reading the answers.

### Step 1
1. Why does `DATABASE_URL` use `db` as the host and not `localhost`?
2. If 10 requests hit `/health/db` at once, how many times does `get_session`'s cleanup run, and how many times does `lifespan`'s?
3. A test creates rows in the database. Why are they gone when the next test starts, even if the code under test called `commit()`?

#### Show answers
1. Each container has its own `localhost`. Inside the API container, `localhost` is the API container itself, where no Postgres runs. Compose gives each service a hostname on its private network, so `db` points to the Postgres container.
2. `get_session` cleanup: 10 times, once per request. `lifespan` cleanup: zero times. It only runs when the server shuts down.
3. The `db_session` fixture opens an outer transaction and rolls it back after each test. With `join_transaction_mode="create_savepoint"`, the code's `commit()` only commits a savepoint *inside* that outer transaction, so the rollback undoes it too.
