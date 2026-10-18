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

### Step 3c — Cases moving through the workflow (2026-10-18)
**Built:** `core.cases` (one row per file, holding its current status) and the workflow engine in backend/app/core/workflow/service.py, the only code that creates cases or changes their status. `change_status()` does five things:
1. Locks the case row.
2. Checks that the move exists from the current status (otherwise **409**).
3. Checks that the caller has the role for it (otherwise **403**).
4. Updates the status.
5. Writes the audit row and commits both together.

Four endpoints:
- `POST /cases` opens a case.
- `GET /cases/{id}` returns the case plus the actions *you* may take next.
- `POST /cases/{id}/status` makes a move.
- `GET /cases/{id}/history` returns the audit trail (staff only).

Applicants see only their own cases. Someone else's case returns the same 404 as a case that doesn't exist.

**Files:** backend/alembic/versions/0006_cases.py, backend/app/core/workflow/models.py (`Case`), backend/app/core/workflow/service.py, backend/app/core/workflow/schemas.py, backend/app/core/workflow/router.py, backend/app/main.py, backend/tests/core/test_cases.py, backend/tests/core/test_case_race.py
**Try it:**
1. `docker compose exec api alembic upgrade head`
2. Create one user per role with the CLI (step 2b): `applicant`, `records_officer`, `minister`, `director`, `officer`.
3. In `localhost:8000/docs`, log in as the applicant and `POST /cases` with `{"workflow": "etls_application"}`.
4. Log in as the records officer, `GET /cases/1`, and look at `available_actions`. Then `POST /cases/1/status` with `{"to_status": "with_minister", "comment": "Registered"}`.
5. Try something illegal, such as the officer approving straight away, and watch it get a 409 or 403.
6. `GET /cases/1/history` as staff shows every step, with who and when.
- `docker compose exec api pytest tests/core/test_cases.py tests/core/test_case_race.py -v`
**New concepts:** Row locking (`SELECT ... FOR UPDATE`), Hiding existence with 404

### Step 3b — Workflow definitions as data (2026-10-18)
**Built:** three tables that *describe* a workflow. `workflows` holds the process and the role that may start one. `workflow_statuses` holds its steps, with one marked initial and some marked final. `workflow_transitions` holds the allowed moves, each with the role that may make it. The database refuses a second initial status and refuses a move that points into another workflow's status. Migration `0005` seeds a placeholder ETLS workflow `[CONFIRM]`. Tests check that every workflow has exactly one start, no dead ends, no moves out of final statuses, and no unreachable statuses.
**Files:** backend/alembic/versions/0004_workflow_definitions.py, backend/alembic/versions/0005_seed_etls_workflow.py, backend/app/core/workflow/models.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose exec api alembic upgrade head`
- See the ETLS moves as a table:
  ```
  docker compose exec db psql -U motie -d motie -c "SELECT f.code AS from_status, t.code AS to_status, r.code AS role, x.name FROM core.workflow_transitions x JOIN core.workflow_statuses f ON f.id = x.from_status_id JOIN core.workflow_statuses t ON t.id = x.to_status_id JOIN core.roles r ON r.id = x.required_role_id ORDER BY x.id"
  ```
- `docker compose exec api pytest tests/core/test_workflow_definitions.py -v`
**The placeholder ETLS workflow:**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister, or permanent_secretary)--> with_directorate
with_directorate --(director: Assign to an officer)--> with_officer
with_officer --(officer)--> approved | rejected | back to with_directorate
```
**New concepts:** State machine, Composite foreign keys, Partial unique index, Data migrations

### Step 3a — Append-only audit log (2026-10-18)
**Built:** `core.audit_log`, one row per event: who, what action, which record, when, and details as JSON. Postgres triggers reject every `UPDATE`, `DELETE` and `TRUNCATE` on it, so history can't be rewritten even with raw SQL. `record_event()` adds a row to the *current* transaction without committing, so the change and its audit row are saved together. `history()` lists a record's events, oldest first.
**Files:** backend/alembic/versions/0003_audit_log.py, backend/app/core/audit/models.py, backend/app/core/audit/service.py, backend/app/models.py, backend/tests/core/test_audit.py
**Try it:**
- `docker compose exec api alembic upgrade head`
- See the protection yourself: `docker compose exec db psql -U motie -d motie -c "DELETE FROM core.audit_log"` gives `ERROR: core.audit_log is append-only: DELETE is not allowed`.
- `docker compose exec api pytest tests/core/test_audit.py -v`
**New concepts:** Append-only audit log, Database triggers, Transactions (all-or-nothing)

### Step 2c — Login with tokens (2026-10-18)
**Built:** `POST /auth/login` checks email and password and returns a signed token (JWT) valid for 60 minutes. `GET /auth/me` returns who the token belongs to. `get_current_user` and `require_role(...)` are the dependencies every protected endpoint will use. Login failures all look identical (same status, same message, same timing), so nobody can probe which emails have accounts.
**Files:** backend/app/core/identity/security.py (tokens), backend/app/core/identity/service.py (`authenticate`), backend/app/core/identity/deps.py, backend/app/core/identity/schemas.py, backend/app/core/identity/router.py, backend/app/core/config.py, backend/app/main.py, docker-compose.yml, .env.example, backend/tests/core/test_auth.py, backend/tests/conftest.py (`make_user`, `auth_headers`)
**Try it:**
- **Your `.env` now needs `JWT_SECRET`.** I added a generated one to your local `.env`. On any other machine, generate one as `.env.example` shows. Compose refuses to start without it.
- `docker compose up --build`, create a user with the CLI (step 2b), then open `localhost:8000/docs`. Run `POST /auth/login`, copy the `access_token`, click **Authorize**, paste it, and run `GET /auth/me`.
- Or with curl: `curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" -d '{"email":"you@motie.gov.gm","password":"..."}'`
- `docker compose exec api pytest tests/core/test_auth.py -v`
**New concepts:** JWT access tokens, Authentication vs authorization (401 vs 403), User enumeration

### Step 2b — Roles and users (2026-10-18)
**Built:** three tables in `core`. `roles` comes pre-filled with placeholder Ministry roles `[CONFIRM]`. `users` holds email, name, an Argon2 password hash, an active flag and a creation time. `user_roles` links them, because one person can hold several roles. A service function `create_user` enforces the rules: lowercase unique email, known roles only, password at least 12 characters. A CLI creates users from the terminal. A new test fails if the Python table classes and the migrations ever disagree.
**Files:** backend/alembic/versions/0002_roles_and_users.py, backend/app/core/identity/models.py, backend/app/core/identity/security.py, backend/app/core/identity/service.py, backend/app/core/identity/cli.py, backend/app/models.py, backend/tests/core/test_users.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose up --build` (new library: pwdlib), then `docker compose exec api alembic upgrade head`.
- Create your own admin: `docker compose exec api python -m app.core.identity.cli create-user --email you@motie.gov.gm --name "Your Name" --role admin`
- Look at the result in psql: `docker compose exec db psql -U motie -d motie -c "SELECT id, email, left(password_hash, 30) FROM core.users"`. The hash starts with `$argon2id$`.
- `docker compose exec api pytest -v`
**New concepts:** Password hashing, ORM models vs migrations

### Step 2a — Alembic and the core schema (2026-10-18)
**Built:** Alembic migrations, set up for our async engine. Migration `0001` creates the `core` schema, where all shared tables will live. The test suite now rebuilds `motie_test` from the migrations on every run, and one test downgrades everything and upgrades again to prove every migration can be rolled back.
**Files:** backend/alembic.ini, backend/alembic/env.py, backend/alembic/versions/0001_core_schema.py, backend/app/db/base.py, backend/app/models.py, backend/tests/conftest.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose exec api alembic upgrade head` applies migrations to your dev database. Run this after pulling new migrations.
- `docker compose exec api alembic current` shows which migration the database is at.
- `docker compose exec api alembic upgrade head --sql` prints the SQL without running it.
- `docker compose exec api pytest -v`
**New concepts:** Database migrations, Postgres schemas

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

### Database migrations
**What:** numbered scripts that change the database structure step by step. Each has an `upgrade()` (apply the change) and a `downgrade()` (undo it). Alembic records the current number in a small `alembic_version` table, so `alembic upgrade head` runs only the scripts a database hasn't had yet. Every copy of the database (yours, the test one, the Ministry server) ends up identical.
**Here:** backend/alembic/versions/: one file per change, named `NNNN_description.py`. backend/alembic/env.py connects Alembic to our database.
**Learn more:** [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

### Postgres schemas
**What:** a schema is a named folder for tables inside one database. `core.users` and `etls.users` would be two different tables. We use one schema per module so modules can't collide, and so permissions can later be granted per module.
**Here:** backend/alembic/versions/0001_core_schema.py creates `core`. Table classes will set `__table_args__ = {"schema": "core"}`.
**Learn more:** [PostgreSQL docs: Schemas](https://www.postgresql.org/docs/16/ddl-schemas.html)

### Password hashing
**What:** we never store passwords. We store a *hash*, a one-way scramble that can check a password but can't be turned back into it. Argon2 is built to be slow and to need a lot of memory, so an attacker who steals the users table can only try a few guesses per second per machine. Each hash includes a random *salt*, so identical passwords give different hashes.
**Here:** backend/app/core/identity/security.py: `hash_password()` and `verify_password()`.
**Learn more:** [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

### ORM models vs migrations
**What:** two descriptions of the same tables. *Migrations* actually build the tables in Postgres, step by step. *Models* (Python classes like `User`) let the code read and write rows without hand-written SQL. They must agree, so `test_models_match_migrations` asks Alembic to compare them and fails on any difference.
**Here:** backend/app/core/identity/models.py (models), backend/alembic/versions/0002_roles_and_users.py (migration), backend/tests/test_migrations.py (the check).
**Learn more:** [SQLAlchemy ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)

### JWT access tokens
**What:** a JWT is a small piece of text with three parts: header, payload (here: user id and expiry time) and a *signature*. The server makes the signature with `JWT_SECRET`, so if anyone changes the payload, or makes a token without the secret, the signature check fails. The payload is only encoded, **not encrypted**: never put secrets in it. Paste a token into jwt.io to see.
**Here:** backend/app/core/identity/security.py: `create_access_token()` and `decode_access_token()`. backend/app/core/identity/deps.py: `get_current_user()` checks the token on each request.
**Learn more:** [Introduction to JSON Web Tokens (jwt.io)](https://jwt.io/introduction)

### Authentication vs authorization (401 vs 403)
**What:** *authentication* asks "who are you?". If we can't tell (no token, bad token), the answer is **401 Unauthorized**. *Authorization* asks "are you allowed to do this?". If we know who you are but the answer is no, it's **403 Forbidden**.
**Here:** backend/app/core/identity/deps.py: `get_current_user()` raises 401, `require_role()` raises 403.
**Learn more:** [MDN: 401](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401), [MDN: 403](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403)

### User enumeration
**What:** if a login form says "no such email" for one email and "wrong password" for another, an attacker learns which emails have accounts and can target them. Response *time* can leak the same thing: checking a password hash is slow, and skipping it for unknown emails is fast. So we return one message and always do a hash check.
**Here:** backend/app/core/identity/service.py: `authenticate()` and `_dummy_hash()`. backend/app/core/identity/router.py: `login()`.
**Learn more:** [OWASP Authentication Cheat Sheet: authentication responses](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html#authentication-and-error-messages)

### Append-only audit log
**What:** a record of everything that happened, where rows are only ever added, never changed or deleted. If someone could edit it, it would prove nothing. For a Ministry, the log answers "who approved this, and when?" years later.
**Here:** backend/app/core/audit/service.py: `record_event()` and `history()`. The rule is enforced in backend/alembic/versions/0003_audit_log.py.
**Learn more:** [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

### Database triggers
**What:** a function that Postgres runs automatically before or after certain statements on a table. Ours runs *before* any UPDATE, DELETE or TRUNCATE on `core.audit_log` and raises an error, which cancels the statement. Because it lives in the database, it protects the table from every client: our API, psql, a future reporting tool.
**Here:** backend/alembic/versions/0003_audit_log.py: `core.audit_log_block_changes()` and the two `CREATE TRIGGER` statements.
**Learn more:** [PostgreSQL docs: Triggers](https://www.postgresql.org/docs/16/plpgsql-trigger.html)

### Transactions (all-or-nothing)
**What:** a group of SQL statements that Postgres saves together at `COMMIT`, or not at all if anything fails (`ROLLBACK`). That's why `record_event()` doesn't commit: the caller changes the record, adds the audit row, then commits once. A crash in between leaves neither change behind.
**Here:** backend/app/core/audit/service.py `record_event()` (adds, never commits). Step 3c's `change_status()` uses it.
**Learn more:** [PostgreSQL tutorial: Transactions](https://www.postgresql.org/docs/16/tutorial-transactions.html)

### State machine
**What:** a model with a fixed set of *states* (our statuses) and a fixed set of allowed *transitions* between them. Anything not on the list is impossible. A file can't jump from "Submitted" to "Approved" just because someone sent that request. Storing the states and transitions in tables ("workflows are data") means a new Ministry process is new rows, not new code.
**Here:** the tables are in backend/alembic/versions/0004_workflow_definitions.py and the classes in backend/app/core/workflow/models.py. Step 3c's `change_status()` enforces them.
**Learn more:** [Wikipedia: Finite-state machine](https://en.wikipedia.org/wiki/Finite-state_machine). Read the turnstile example.

### Composite foreign keys
**What:** a foreign key over *two* columns together. `workflow_transitions(workflow_id, to_status_id)` must match a row in `workflow_statuses(workflow_id, id)`. A plain key on `to_status_id` alone would accept *any* status, even one from a different workflow. The pair forces both to agree.
**Here:** `workflow_transitions_from_fkey` and `workflow_transitions_to_fkey` in backend/alembic/versions/0004_workflow_definitions.py. They need the matching `UNIQUE (workflow_id, id)` on `workflow_statuses`.
**Learn more:** [PostgreSQL docs: Foreign keys](https://www.postgresql.org/docs/16/ddl-constraints.html#DDL-CONSTRAINTS-FK)

### Partial unique index
**What:** a unique rule that applies only to rows matching a condition. `UNIQUE (workflow_id) WHERE is_initial` means a workflow can have many statuses, but only one of them with `is_initial = true`.
**Here:** `workflow_statuses_one_initial` in backend/alembic/versions/0004_workflow_definitions.py.
**Learn more:** [PostgreSQL docs: Partial indexes](https://www.postgresql.org/docs/16/indexes-partial.html)

### Data migrations
**What:** a migration that inserts or changes *rows* rather than table structure. We use one to load the ETLS workflow, so every database gets exactly the same definition. Rows are looked up by `code`, never by `id`, because ids can differ between databases.
**Here:** backend/alembic/versions/0005_seed_etls_workflow.py. Also the role list at the end of 0002.
**Learn more:** [Alembic cookbook: data migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#data-migrations-general-techniques)

### Row locking (`SELECT ... FOR UPDATE`)
**What:** two officers press "Approve" and "Reject" on the same file in the same second. Without care, both requests read "With the officer", both decide their move is allowed, and both save: the file is approved *and* rejected. `FOR UPDATE` locks the row when it's read. The second request waits until the first commits, then reads the *new* status (final) and is refused.
**Here:** backend/app/core/workflow/service.py: `get_case(..., for_update=True)`, used by `change_status()`. Proven by backend/tests/core/test_case_race.py, which fails if you remove the lock (we tried it: 3 out of 3 failures).
**Learn more:** [PostgreSQL docs: Row-level locks](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)

### Hiding existence with 404
**What:** if `/cases/41` said "403 not yours" and `/cases/9999` said "404 not found", an applicant could count how many cases exist, or test which ids are real. Returning the same 404 for both reveals nothing. We use 403 only when the user is allowed to *see* the thing but not to *do* the action.
**Here:** backend/app/core/workflow/service.py `get_case()`. Tested by `test_applicants_only_see_their_own_cases`.
**Learn more:** [OWASP: Insecure Direct Object Reference](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)

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
| 2026-10-18 | Migrations written by hand, with short numbered IDs (`0001`, `0002`, ...) | `alembic revision --autogenerate` with random IDs | You can read each migration top to bottom and know exactly what SQL runs. Numbers show the order at a glance. Autogenerate is still available as a starting point. |
| 2026-10-18 | Migrations run by a manual command, not on API startup | auto-migrate when the API starts | On the Ministry server, a schema change should be a deliberate step someone watches, ideally after a backup. |
| 2026-10-18 | Test database dropped and rebuilt every test run | keep it between runs | It always matches the current migrations, even after you edit one. Costs about a second. |
| 2026-10-18 | `alembic_version` table stays in the `public` schema | put it in `core` | Alembic creates that table *before* running migration 0001, so `core` wouldn't exist yet. |
| 2026-10-18 | Users log in with email | a separate username | Applicants need an email for notifications anyway, so one identifier works for staff and applicants alike. |
| 2026-10-18 | A user can hold several roles (`user_roles` link table) | one role column on `users` | A Director may also act as an officer. Adding a role is then a row, not a schema change. |
| 2026-10-18 | Roles hold permissions; positions and delegation come later with the workflow | positions now | Step 2 is "users and roles". Approvals will attach to positions, as CLAUDE.md requires, when we build that. |
| 2026-10-18 | Numeric IDs (`BIGINT` identity) | UUIDs | Simpler to read and debug. IDs in URLs can be guessed, so every endpoint must check permissions anyway, which it would need to with UUIDs too. |
| 2026-10-18 | Users are deactivated, never deleted | allow delete | The audit log must always be able to say who did what. |
| 2026-10-18 | Minimum password length 12, no complexity rules | 8 characters plus symbols | Follows NIST SP 800-63B: length matters more than symbols. |
| 2026-10-18 | Service functions own the transaction (they call `commit()`) | endpoints commit | One place decides what is saved together. Matters most for "status change + audit row" in step 3. |
| 2026-10-18 | Users created by a CLI with a password prompt | seed an admin from `.env`; an admin API endpoint | No password ever sits in a file or shell history. An admin UI can come later. |
| 2026-10-18 | JWT access tokens (PyJWT, HS256), 60-minute lifetime | server-side sessions in a table | Approved by you. No session table to clean up. The weakness is that a token can't be "taken back" before it expires, which the next row works around. |
| 2026-10-18 | The token holds only the user id; user and roles are reloaded from the database on every request | put roles in the token | Deactivating a user or removing a role works immediately, not after up to 60 minutes. The cost is one small query per request. |
| 2026-10-18 | No refresh tokens yet | short access token + long refresh token | Keeps step 2 small. Users log in again after 60 minutes. Revisit with the frontend. |
| 2026-10-18 | Login takes a JSON body | OAuth2 password form (`OAuth2PasswordRequestForm`) | The form version needs another library (`python-multipart`). JSON is all the Next.js frontend needs. |
| 2026-10-18 | `JWT_SECRET` must be at least 32 characters, or the app won't start | accept anything | A short secret can be brute-forced, which would let someone forge logins as anyone. |
| 2026-10-18 | Append-only enforced by a database trigger | only "be careful in Python"; `REVOKE UPDATE, DELETE` permissions | A trigger protects against every client, and works even while the app connects as the table owner. Revoking permissions is added before go-live (see Open questions). |
| 2026-10-18 | One generic audit table (`entity_type` + `entity_id` + JSON `details`) | a separate history table per record type | Every module can log to it, and "show everything user X did" is one query. |
| 2026-10-18 | `record_event()` never commits | commit inside it | So a change and its audit row are always saved in the same transaction. |
| 2026-10-18 | Transitions name a required *role* for now | name a *position* (e.g. "Director of Trade") | CLAUDE.md says approvals attach to positions, with delegation for absences. Positions need their own tables. Until then, roles keep the engine working, and switching the column later is one migration. |
| 2026-10-18 | The PS gets the Minister's move as a second transition row | delegation | Placeholder for "PS when the Minister is away". With real delegation, the PS row goes and the Minister delegates when absent. |
| 2026-10-18 | One role may start a workflow (`workflows.start_role_id`) | a link table allowing several roles | Enough for ETLS. Becomes a table if Records also needs to open cases for walk-in applicants (see Open questions). |
| 2026-10-18 | The ETLS definition is seeded in the shared migration chain | a separate `etls` module migration | There's only one Alembic chain so far. When the `etls` schema arrives, its data can move with it. |
| 2026-10-18 | Database constraints guard the workflow's structure; tests guard its logic | everything in Python | Constraints (one initial status, statuses from the same workflow) protect against any client. Rules like "no dead ends" need a whole-graph check, which is easier as a test. |
| 2026-10-18 | The generic table is called `cases` | `files`, `requests`, `applications` | "File" collides with uploaded documents, which come later. "Application" is ETLS-specific. Module tables (e.g. `etls.applications`) will point at `core.cases.id`. |
| 2026-10-18 | The case's history lives only in `core.audit_log` | a separate `case_status_history` table | One source of truth. A second table could disagree with the audit log. |
| 2026-10-18 | Pessimistic locking (`FOR UPDATE`) | optimistic locking (a version number, retry on conflict) | Simpler to read, and contention is tiny (a handful of officers per file). No retry logic needed. |
| 2026-10-18 | 409 for "move not possible from here", 403 for "move exists but not for your role" | 400 for both | The frontend can show "this file has already moved on" (409) differently from "you can't do this" (403). |
| 2026-10-18 | Engine errors are Python exceptions, turned into HTTP codes in one handler | raise `HTTPException` inside the service | The service stays usable from the CLI, background jobs and tests, without knowing about HTTP. |
| 2026-10-18 | Applicants can't read the history | show applicants everything | History holds internal minutes and comments. Applicants see the current status only, until the Ministry decides otherwise. |

## 4. Open questions

Items marked `[CONFIRM]` in the code, to check with the Ministry.

- [ ] **Role list:** is `applicant, records_officer, minister, permanent_secretary, director, officer, admin` right? Are there other roles (e.g. Deputy PS, Registrar)? See backend/alembic/versions/0002_roles_and_users.py.
- [ ] **Staff password policy:** does the Government of The Gambia have an ICT policy we must follow (length, expiry, two-factor)?
- [ ] **Session length:** is 60 minutes before re-login acceptable for officers? (`ACCESS_TOKEN_MINUTES` in settings.)
- [ ] **Security to-do before going live (not a Ministry question):** rate-limit `/auth/login` against password guessing, and serve the API only over HTTPS. Tokens sent over plain HTTP can be stolen.
- [ ] **Security to-do before going live:** the app connects as the database owner (`POSTGRES_USER`), who can disable triggers. Create a separate app database user with no rights to `ALTER` tables or to `UPDATE`/`DELETE` on `core.audit_log`.
- [ ] **Audit retention:** how long must audit records be kept under Gambian public records rules?
- [ ] **ETLS workflow steps:** is Submitted → Minister → Directorate → Officer → Approved/Rejected the real path? Are there steps such as "returned to applicant for more documents", a fee payment, or an inspection? See backend/alembic/versions/0005_seed_etls_workflow.py.
- [ ] **Who signs the ETLS approval:** the subject officer, the Director, or the Minister/PS?
- [ ] **Who may open an ETLS case:** only the applicant online, or can Records register walk-in applications too?
- [ ] **Who may see a case:** right now, any staff member sees every case. Should staff see only cases in their directorate, or only cases assigned to them? See `can_view()` in backend/app/core/workflow/service.py.
- [ ] **What applicants see:** only the current status, or also the steps taken (without internal comments)? See `case_history()` in backend/app/core/workflow/router.py.
- [ ] **Deadlines:** how many days may a file sit at each step before it's overdue? (Needed for deadline tracking, not built yet.)

## 5. Check yourself

Questions per step. Try to answer before reading the answers.

### Step 3c
1. An officer sends `{"to_status": "approved"}` for a case that is still "Submitted". Which status code comes back, and which line decides it? Does anything get written to the audit log?
2. Why does `get_case()` use `populate_existing=True` together with `with_for_update()`?
3. An applicant asks for `GET /cases/57`, which belongs to another applicant. What do they get, and why not 403?

#### Show answers
1. **409 Conflict.** In `change_status()`, the query for moves from `submitted` to `approved` finds no rows, so it raises `TransitionNotAllowed`, which `_ERROR_STATUS` in router.py maps to 409. Nothing is written: the exception happens before `record_event()`, and nothing was committed.
2. The lock makes a second request wait. But if the session already had the case in memory, SQLAlchemy would hand back the old copy with the old status. `populate_existing` forces it to use the freshly read row, so the decision is based on the status *after* the other request committed.
3. **404 "Case not found."**, the same answer as for a case that doesn't exist. A 403 would confirm that case 57 exists, letting someone map out the Ministry's case ids.

### Step 3b
1. The Ministry says Directors may now reject a file directly from "With the Directorate". What do you change: Python code, or something else?
2. Why does `workflow_transitions` reference `(workflow_id, to_status_id)` together instead of just `to_status_id`?
3. In the seed migration, what happens if someone misspells `'with_officer'` as `'with_oficer'` in a transition row, and what catches it?

#### Show answers
1. Something else: a new migration that inserts one row into `core.workflow_transitions` (`with_directorate` → `rejected`, role `director`). No Python changes, because workflows are data.
2. So a transition can only point to a status in its *own* workflow. With `to_status_id` alone, a move could lead into another process's status, and a case would end up stuck in a workflow it doesn't belong to.
3. The `JOIN` on the status code finds no match, so that row is silently left out. `test_etls_workflow_is_seeded` expects exactly 7 transitions and fails. `test_every_workflow_is_well_formed` would probably also report a dead end.

### Step 3a
1. Why doesn't `record_event()` call `session.commit()`?
2. Someone with psql access runs `UPDATE core.audit_log SET actor_user_id = 3 WHERE id = 10`. What happens? Is there still a way around it?
3. Why is `entity_id` a text column and not a number?

#### Show answers
1. So the change and its audit row are committed together, in one transaction. If `record_event()` committed on its own, a crash between the two commits could leave an audit row for a change that never happened, or a change with no audit row.
2. The trigger `audit_log_no_update_delete` raises an error and the update is cancelled. The way around it is that the table owner or a superuser can disable the trigger. That's why the go-live to-do is to connect the app as a less-privileged database user.
3. Different modules may use different kinds of keys (numbers, reference codes like `ETLS-2026-0001`). Text can hold any of them.

### Step 2c
1. An officer is dismissed at 10:00 and an admin sets `is_active = false`. Their token was issued at 9:30 and expires at 10:30. Can they still use the API at 10:05? Why?
2. Someone edits their token's payload to change `"sub": "7"` into `"sub": "1"` (the admin). What happens, and which line of code stops it?
3. Why does `authenticate()` hash a dummy password when the email doesn't exist?

#### Show answers
1. No. `get_current_user()` in backend/app/core/identity/deps.py loads the user from the database on every request and rejects inactive users with 401, even if the token itself is still valid.
2. The signature no longer matches the payload, so `jwt.decode(...)` in `decode_access_token()` raises `InvalidTokenError` and they get 401. Making a valid signature needs `JWT_SECRET`, which only the server has.
3. So the response takes the same time whether or not the email exists. Otherwise an attacker could time the responses to find out which emails have accounts (user enumeration).

### Step 2b
1. An attacker copies the whole `core.users` table. Why can't they just read the passwords, and why does Argon2 being slow matter?
2. You add a `phone` attribute to the `User` class but forget the migration. What catches it?
3. Why does `User.roles` use `lazy="selectin"`?

#### Show answers
1. The table only holds hashes, which can't be reversed. The attacker has to guess passwords and hash each guess. Argon2 makes each guess slow and memory-hungry, and the per-user salt means they must attack each user separately.
2. `test_models_match_migrations` in backend/tests/test_migrations.py. Alembic finds a column in the model that the database doesn't have, and the test fails.
3. With async SQLAlchemy, a relationship can't be fetched silently the first time you touch it (that would need hidden I/O). `selectin` loads the roles in one extra query right when the user is loaded.

### Step 2a
1. You pull new code that contains migration `0003`. Your database is at `0002`. What command do you run, and which migrations does it execute?
2. Why does `0001`'s `downgrade()` use `DROP SCHEMA core` without `CASCADE`?
3. Where does Alembic get the database password from, and why isn't it in `alembic.ini`?

#### Show answers
1. `docker compose exec api alembic upgrade head`. It reads `alembic_version` (0002) and runs only `0003`.
2. `CASCADE` would silently delete every table inside `core`. Without it, Postgres refuses if tables still exist, which protects you from losing data with a mistaken downgrade.
3. From `DATABASE_URL`, read by `get_url()` in backend/alembic/env.py (via `settings`). `alembic.ini` is committed to git, and passwords must never be in committed files.

### Step 1
1. Why does `DATABASE_URL` use `db` as the host and not `localhost`?
2. If 10 requests hit `/health/db` at once, how many times does `get_session`'s cleanup run, and how many times does `lifespan`'s?
3. A test creates rows in the database. Why are they gone when the next test starts, even if the code under test called `commit()`?

#### Show answers
1. Each container has its own `localhost`. Inside the API container, `localhost` is the API container itself, where no Postgres runs. Compose gives each service a hostname on its private network, so `db` points to the Postgres container.
2. `get_session` cleanup: 10 times, once per request. `lifespan` cleanup: zero times. It only runs when the server shuts down.
3. The `db_session` fixture opens an outer transaction and rolls it back after each test. With `join_transaction_mode="create_savepoint"`, the code's `commit()` only commits a savepoint *inside* that outer transaction, so the rollback undoes it too.
