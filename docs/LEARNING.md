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

### Step 5b — Succession orders (2026-10-19)
**Built:** `core.succession_orders`, the Ministry's standing rule for who is next in line when a post's holder is away. Each row says "when *post* is absent, *successor* is next, at *rank*", for every workflow or for one. Migration `0013` seeds:

| Post | Workflow | 1st in line | 2nd in line |
| --- | --- | --- | --- |
| Minister | all | Permanent Secretary | DPS Admin & Finance `[CONFIRM]` |
| Permanent Secretary | all | DPS Admin & Finance | |
| Director of Industry and Investment | ETLS only | DPS Admin & Finance | |

`succession_order()` in backend/app/core/workflow/succession.py returns the line for a post and a workflow. If a post has rows for that workflow, they *replace* its general rows. Nothing uses the table yet: step 5c records absences, and step 5d lets the engine act on them.

**Files:** backend/alembic/versions/0013_succession_orders.py, backend/app/core/workflow/models.py (`SuccessionStep`), backend/app/core/workflow/succession.py, backend/tests/core/test_succession.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- `docker compose exec db psql -U motie -d motie -c "SELECT p.code AS post, w.code AS workflow, s.rank, n.code AS next_in_line FROM core.succession_orders s JOIN core.positions p ON p.id = s.position_id JOIN core.positions n ON n.id = s.successor_position_id LEFT JOIN core.workflows w ON w.id = s.workflow_id ORDER BY p.code, s.rank"`
- `docker compose run --rm tools pytest tests/core/test_succession.py -v`
**New concepts:** NULL in unique constraints (`NULLS NOT DISTINCT`)

### Step 5a — The confirmed ETLS route (2026-10-19)
**Built:** migration `0012` turns the placeholder ETLS workflow into the route the Ministry confirmed:
- New posts: Director of Industry and Investment (`director_of_industry`), an Industry and Investment Officer (`industry_officer`) and the Deputy PS, Administration and Finance (`dps_admin_finance`), with their departments.
- The ETLS route now goes through the PS. The Director's single step, "Sign and assign to an officer", covers both signing and minuting the file to an officer.
- The Trade posts stay in the org chart, but ETLS no longer uses them.

```
submitted     --(records_officer: Register and forward to the Minister)--> with_minister
with_minister --(minister: Minute to the Permanent Secretary)-----------> with_ps
with_ps       --(permanent_secretary: Minute to the Director)-----------> with_director
with_director --(director_of_industry: Sign and assign to an officer)----> with_officer
with_officer  --(industry_officer)--> approved | rejected | back to with_director   [CONFIRM]
```
The old "With the Directorate" status was *renamed* to `with_director`, not replaced, so a case already in it keeps a valid status. The officer's three moves are still placeholders: the Ministry hasn't said what the officer does after the Director signs, or who may reject.

The race test now gives its posts back when it ends (`release_posts`). It commits for real, and from step 5d a leftover "race" Minister would count as present in other tests.

**Files:** backend/alembic/versions/0012_confirmed_etls_route.py, backend/tests/core/conftest.py (`STAFF` replaces `POSITION_FOR`, and adds the DPS), backend/tests/core/test_cases.py, backend/tests/core/test_case_race.py, backend/tests/core/test_delegations.py, backend/tests/core/test_workflow_definitions.py (`test_etls_route_is_the_one_the_ministry_confirmed`), backend/tests/core/test_positions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then the transitions query from step 4c: 7 rows, matching the diagram.
- `docker compose run --rm tools pytest tests/core/test_workflow_definitions.py tests/core/test_cases.py -v`
**New concepts:** none. See Data migrations, and Changing a column with existing data (expand, backfill, contract).

### Step 4e — The PS acts for the Minister through delegation (2026-10-19)
**Built:** migration `0011` removes the placeholder transition from step 3b that let the Permanent Secretary *always* make the Minister's move. Now the PS can only do it while the Minister's post has delegated to the PS post (step 4d). The audit row then says `"as_position": "permanent_secretary", "on_behalf_of": "minister"`. Without a delegation, the PS gets 403 and sees no button.

**The ETLS moves now (6, down from 7):**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister: Minute to the Directorate)--> with_directorate
with_directorate --(director_of_trade: Assign to an officer)--> with_officer
with_officer --(trade_officer)--> approved | rejected | back to with_directorate
Any of these can also be made by a post the required post has delegated to.
```
**Tests changed, and why:**
- `test_permanent_secretary_can_act_for_the_minister` now first has the Minister delegate for a week (`_minister_is_away`). Its original assertions are unchanged and still pass, and it also checks `on_behalf_of`.
- `test_etls_workflow_is_seeded` now expects 6 transitions, not 7, because the row really is gone.
- New: `test_permanent_secretary_cannot_act_for_the_minister_without_a_delegation`.

**Files:** backend/alembic/versions/0011_remove_ps_placeholder_move.py, backend/tests/core/test_cases.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then rerun the transitions query from step 4c: 6 rows, no `permanent_secretary`.
- Walk a case to "With the Minister". As the PS, `GET /cases/1` shows no actions. As the Minister, `POST /delegations` with `{"from_position": "minister", "to_position": "permanent_secretary", "starts_on": "<today>", "ends_on": "<today + 6 days>"}`. As the PS, the "Minute to the Directorate" button appears with `"on_behalf_of": "minister"`.
- `docker compose run --rm tools pytest tests/core/test_cases.py -v`
**New concepts:** none. This step uses Delegation (acting on behalf of) from step 4d.

### Step 4d — Delegation (2026-10-19)
**Built:** `core.delegations`. A holder of a post can let another post act for it from one date to another, both days included, either for every workflow or for one. Example: the Director of Trade is on leave from 3 to 10 March and delegates to the Trade Officer post.
- The engine now tries the actor's own posts first, then any delegation active *today* to a post they hold. `change_status()` records three keys in the audit row: `as_position` (the post the actor acted from), `on_behalf_of` (whose authority they used, or `null`) and `delegation_id`.
- `GET /cases/{id}` marks borrowed moves: `"on_behalf_of": "director_of_trade"`.
- Rules (backend/app/core/workflow/delegation.py): only a holder of the post may delegate or revoke it. No delegating to yourself, no back-dating, at most 90 days `[CONFIRM]`. Delegations aren't passed on: a delegate can't hand the borrowed powers to someone else. The delegating post keeps its own powers.
- A delegation is ended early by *revoking* it. It's never deleted or edited: the app may only set `revoked_at`/`revoked_by` (a column-level grant), so nobody can stretch the dates afterwards to cover an earlier action.

Endpoints:
- `POST /delegations` creates one.
- `GET /delegations` lists current and upcoming ones given by, or to, your posts.
- `POST /delegations/{id}/revoke` ends one.

The workflow engine's errors moved to backend/app/core/workflow/errors.py, so the delegation code can use them too. A broken delegation rule returns **422**; revoking twice returns **409**.

**Files:** backend/alembic/versions/0010_delegations.py, backend/app/core/workflow/models.py (`Delegation`), backend/app/core/workflow/delegation.py, backend/app/core/workflow/delegation_router.py, backend/app/core/workflow/errors.py, backend/app/core/workflow/service.py (`PermittedMove`, `_permitted()`, `change_status()`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/main.py, backend/tests/core/test_delegations.py, backend/tests/core/conftest.py (`people`, `act`, moved from test_cases.py), backend/tests/support.py (`open_case`, `move`), backend/tests/core/test_db_privileges.py
**Try it:**
1. `docker compose run --rm tools alembic upgrade head`
2. Set up the step 4c users with their posts and walk a case to "With the Directorate".
3. Log in as the Trade Officer: `GET /cases/1` shows no actions, and moving to `with_officer` gives 403.
4. Log in as the Director and `POST /delegations` with `{"from_position": "director_of_trade", "to_position": "trade_officer", "starts_on": "<today>", "ends_on": "<today + 6 days>", "workflow": "etls_application", "reason": "Annual leave"}`.
5. As the Trade Officer again: `GET /cases/1` now offers "Assign to an officer" with `"on_behalf_of": "director_of_trade"`. Make the move, then look at the last row of `GET /cases/1/history`.
6. As the Director, `POST /delegations/1/revoke`. The officer loses the button.
- `docker compose run --rm tools pytest tests/core/test_delegations.py -v`
**New concepts:** Delegation (acting on behalf of), Column-level privileges, Testing with a fake "today" (monkeypatch)

### Step 4c — Approvals belong to positions (2026-10-19)
**Built:** each workflow transition now names the *position* that may make it (`required_position_id`), not a role. Migration `0009` converted the existing ETLS moves with a fixed role-to-post mapping `[CONFIRM]`, then dropped `required_role_id`. The engine (backend/app/core/workflow/service.py) now checks the posts you hold:
- `available_transitions()` lists moves for any post you hold.
- `change_status()` refuses with **403** "None of your positions can make this move" otherwise.
- The audit row records `as_position` (older rows keep their `as_role`; the log is append-only).

Roles still decide what *kind* of user you are: who may open an ETLS case (applicants) and who may see case history (staff). Holding the `director` role without the Director of Trade post no longer lets you assign files.

**The ETLS moves now:**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister, or permanent_secretary)--> with_directorate
with_directorate --(director_of_trade: Assign to an officer)--> with_officer
with_officer --(trade_officer)--> approved | rejected | back to with_directorate
```
**Files:** backend/alembic/versions/0009_transitions_require_positions.py, backend/app/core/workflow/models.py (`WorkflowTransition.required_position`), backend/app/core/workflow/service.py, backend/app/core/identity/service.py (`create_user` now loads `positions`), backend/tests/core/test_cases.py (`POSITION_FOR`, two new tests), backend/tests/core/test_case_race.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- See which post makes each move:
  ```
  docker compose exec db psql -U motie -d motie -c "SELECT f.code AS from_status, t.code AS to_status, p.code AS position, x.name FROM core.workflow_transitions x JOIN core.workflow_statuses f ON f.id = x.from_status_id JOIN core.workflow_statuses t ON t.id = x.to_status_id JOIN core.positions p ON p.id = x.required_position_id ORDER BY x.id"
  ```
- Create staff users as in step 3c, then give each a post with `assign-position` (step 4b): `records_officer`, `minister`, `director_of_trade`, `trade_officer`. Without the post, the same user gets 403.
- `docker compose run --rm tools pytest tests/core/test_cases.py -v`. Read `test_the_position_decides_not_the_role` and `test_a_new_post_holder_takes_over_at_once`.
**New concepts:** Changing a column with existing data (expand, backfill, contract)

### Step 4b — Departments, positions and who holds them (2026-10-19)
**Built:** three tables in `core`:
- `departments`: the Ministry's units.
- `positions`: posts such as "Director of Trade". Each belongs to a department and has a `reports_to_id` pointing at the post above it.
- `position_holders`: which user holds which post.

A user can hold several posts (an officer acting as Director), and a post can have several holders (several Trade Officers). Migration `0008` seeds a placeholder org chart `[CONFIRM]`. `assign_position()` and `remove_position()` change holders and write an audit row (`position.assigned` / `position.removed`) for each real change. `/auth/me` now lists your positions. Nothing uses positions for approvals yet; that's step 4c.

**The placeholder org chart:**
```
Minister (Office of the Minister)
└── Permanent Secretary (Office of the PS)
    ├── Records Officer (Registry)
    └── Director of Trade (Directorate of Trade)
        └── Trade Officer (Directorate of Trade)
```
**Files:** backend/alembic/versions/0008_positions.py, backend/app/core/identity/models.py (`Department`, `Position`, `position_holders`, `User.positions`), backend/app/core/identity/service.py (`assign_position`, `remove_position`), backend/app/core/identity/cli.py, backend/app/core/identity/schemas.py, backend/app/core/identity/router.py, backend/tests/conftest.py (`make_user(..., positions=[...])`), backend/tests/core/test_positions.py, backend/tests/core/test_auth.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Give a user a post: `docker compose exec api python -m app.core.identity.cli assign-position --email you@motie.gov.gm --position director_of_trade`. Run it twice: the second time it says "Nothing to do". Take it away with `remove-position`.
- Log in and call `GET /auth/me`: `positions` lists your posts.
- See who holds what: `docker compose exec db psql -U motie -d motie -c "SELECT p.title, u.email, h.assigned_at FROM core.position_holders h JOIN core.positions p ON p.id = h.position_id JOIN core.users u ON u.id = h.user_id"`
- `docker compose run --rm tools pytest tests/core/test_positions.py -v`
**New concepts:** Positions vs roles, Self-referencing foreign key, `ON CONFLICT DO NOTHING ... RETURNING`

### Step 4a — Separate database users (2026-10-19)
**Built:** the API no longer logs in to Postgres as the superuser. There are now three database users, each with one job:
- `motie` (`POSTGRES_USER`, the superuser): only used by db/init/10-db-users.sh and to create the test database.
- `motie_owner`: owns the database, the schemas and every table. Migrations run as it.
- `motie_app`: what the API logs in as. It owns nothing, so it can't `ALTER` or `DROP` tables or disable the audit triggers. Migration `0007` grants it only what the API needs, table by table: read-only on roles and workflow definitions, no `DELETE` on users and cases, and only `SELECT` and `INSERT` on the audit log.

Migrations and tests now run in a new one-off `tools` container, which has the owner's password. The long-running `api` container only gets `motie_app`'s.

**Files:** db/init/10-db-users.sh, backend/alembic/versions/0007_app_privileges.py, docker-compose.yml, .env.example, backend/alembic/env.py, backend/app/core/config.py, backend/tests/conftest.py (`owner_session`), backend/tests/core/test_db_privileges.py, backend/tests/core/test_audit.py, backend/tests/core/test_workflow_definitions.py, CLAUDE.md (commands)
**Try it:**
- **Your `.env` needs two new passwords:** `MIGRATION_DB_PASSWORD` and `APP_DB_PASSWORD`. I added generated ones to your local `.env`. On any other machine, copy them from `.env.example` and change them.
- **Commands changed.** Migrations: `docker compose run --rm tools alembic upgrade head`. Tests: `docker compose run --rm tools pytest -v`. `docker compose exec api alembic ...` now stops with "MIGRATION_DATABASE_URL is not set". That's on purpose: the API container doesn't have the owner's password.
- A database created before this step (your dev one, or a server) needs the users script once, then the migration. I've already done both on your dev database:
  ```
  docker compose up -d
  docker compose exec db bash /docker-entrypoint-initdb.d/10-db-users.sh
  docker compose run --rm tools alembic upgrade head
  ```
  On a brand-new volume, Postgres runs the script by itself the first time it starts.
- Try to switch off the audit protection as the app: `docker compose exec db psql -U motie_app -d motie -c "ALTER TABLE core.audit_log DISABLE TRIGGER ALL"` gives `ERROR: must be owner of table audit_log`. The same with `-c "DELETE FROM core.audit_log"` gives `permission denied`.
- `docker compose run --rm tools pytest tests/core/test_db_privileges.py tests/core/test_audit.py -v`
**New concepts:** Least privilege (database users), GRANT and table ownership, One-off containers (Compose profiles)

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
1. `docker compose run --rm tools alembic upgrade head`
2. Create one user per role with the CLI (step 2b): `applicant`, `records_officer`, `minister`, `director`, `officer`.
3. In `localhost:8000/docs`, log in as the applicant and `POST /cases` with `{"workflow": "etls_application"}`.
4. Log in as the records officer, `GET /cases/1`, and look at `available_actions`. Then `POST /cases/1/status` with `{"to_status": "with_minister", "comment": "Registered"}`.
5. Try something illegal, such as the officer approving straight away, and watch it get a 409 or 403.
6. `GET /cases/1/history` as staff shows every step, with who and when.
- `docker compose run --rm tools pytest tests/core/test_cases.py tests/core/test_case_race.py -v`
**New concepts:** Row locking (`SELECT ... FOR UPDATE`), Hiding existence with 404

### Step 3b — Workflow definitions as data (2026-10-18)
**Built:** three tables that *describe* a workflow. `workflows` holds the process and the role that may start one. `workflow_statuses` holds its steps, with one marked initial and some marked final. `workflow_transitions` holds the allowed moves, each with the role that may make it. The database refuses a second initial status and refuses a move that points into another workflow's status. Migration `0005` seeds a placeholder ETLS workflow `[CONFIRM]`. Tests check that every workflow has exactly one start, no dead ends, no moves out of final statuses, and no unreachable statuses.
**Files:** backend/alembic/versions/0004_workflow_definitions.py, backend/alembic/versions/0005_seed_etls_workflow.py, backend/app/core/workflow/models.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- See the ETLS moves as a table (this query is the step 4c version, with positions):
  ```
  docker compose exec db psql -U motie -d motie -c "SELECT f.code AS from_status, t.code AS to_status, p.code AS position, x.name FROM core.workflow_transitions x JOIN core.workflow_statuses f ON f.id = x.from_status_id JOIN core.workflow_statuses t ON t.id = x.to_status_id JOIN core.positions p ON p.id = x.required_position_id ORDER BY x.id"
  ```
- `docker compose run --rm tools pytest tests/core/test_workflow_definitions.py -v`
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
- `docker compose run --rm tools alembic upgrade head`
- See the protection yourself: `docker compose exec db psql -U motie -d motie -c "DELETE FROM core.audit_log"` gives `ERROR: core.audit_log is append-only: DELETE is not allowed`.
- `docker compose run --rm tools pytest tests/core/test_audit.py -v`
**New concepts:** Append-only audit log, Database triggers, Transactions (all-or-nothing)

### Step 2c — Login with tokens (2026-10-18)
**Built:** `POST /auth/login` checks email and password and returns a signed token (JWT) valid for 60 minutes. `GET /auth/me` returns who the token belongs to. `get_current_user` and `require_role(...)` are the dependencies every protected endpoint will use. Login failures all look identical (same status, same message, same timing), so nobody can probe which emails have accounts.
**Files:** backend/app/core/identity/security.py (tokens), backend/app/core/identity/service.py (`authenticate`), backend/app/core/identity/deps.py, backend/app/core/identity/schemas.py, backend/app/core/identity/router.py, backend/app/core/config.py, backend/app/main.py, docker-compose.yml, .env.example, backend/tests/core/test_auth.py, backend/tests/conftest.py (`make_user`, `auth_headers`)
**Try it:**
- **Your `.env` now needs `JWT_SECRET`.** I added a generated one to your local `.env`. On any other machine, generate one as `.env.example` shows. Compose refuses to start without it.
- `docker compose up --build`, create a user with the CLI (step 2b), then open `localhost:8000/docs`. Run `POST /auth/login`, copy the `access_token`, click **Authorize**, paste it, and run `GET /auth/me`.
- Or with curl: `curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" -d '{"email":"you@motie.gov.gm","password":"..."}'`
- `docker compose run --rm tools pytest tests/core/test_auth.py -v`
**New concepts:** JWT access tokens, Authentication vs authorization (401 vs 403), User enumeration

### Step 2b — Roles and users (2026-10-18)
**Built:** three tables in `core`. `roles` comes pre-filled with placeholder Ministry roles `[CONFIRM]`. `users` holds email, name, an Argon2 password hash, an active flag and a creation time. `user_roles` links them, because one person can hold several roles. A service function `create_user` enforces the rules: lowercase unique email, known roles only, password at least 12 characters. A CLI creates users from the terminal. A new test fails if the Python table classes and the migrations ever disagree.
**Files:** backend/alembic/versions/0002_roles_and_users.py, backend/app/core/identity/models.py, backend/app/core/identity/security.py, backend/app/core/identity/service.py, backend/app/core/identity/cli.py, backend/app/models.py, backend/tests/core/test_users.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose up --build` (new library: pwdlib), then `docker compose run --rm tools alembic upgrade head`.
- Create your own admin: `docker compose exec api python -m app.core.identity.cli create-user --email you@motie.gov.gm --name "Your Name" --role admin`
- Look at the result in psql: `docker compose exec db psql -U motie -d motie -c "SELECT id, email, left(password_hash, 30) FROM core.users"`. The hash starts with `$argon2id$`.
- `docker compose run --rm tools pytest -v`
**New concepts:** Password hashing, ORM models vs migrations

### Step 2a — Alembic and the core schema (2026-10-18)
**Built:** Alembic migrations, set up for our async engine. Migration `0001` creates the `core` schema, where all shared tables will live. The test suite now rebuilds `motie_test` from the migrations on every run, and one test downgrades everything and upgrades again to prove every migration can be rolled back.
**Files:** backend/alembic.ini, backend/alembic/env.py, backend/alembic/versions/0001_core_schema.py, backend/app/db/base.py, backend/app/models.py, backend/tests/conftest.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head` applies migrations to your dev database. Run this after pulling new migrations.
- `docker compose run --rm tools alembic current` shows which migration the database is at.
- `docker compose run --rm tools alembic upgrade head --sql` prints the SQL without running it.
- `docker compose run --rm tools pytest -v`
**New concepts:** Database migrations, Postgres schemas

### Step 1 — FastAPI skeleton connected to Postgres (2026-10-18)
**Built:** two Docker Compose services: Postgres 16 (with pgvector available) and the FastAPI app. The app reads `DATABASE_URL`, keeps one connection pool, and exposes `/health` (the process is alive) and `/health/db` (Postgres answers a query). If the database is down, `/health/db` returns 503 with a plain message and logs the full error on the server. Tests run against a separate `motie_test` database.
**Files:** docker-compose.yml, .env.example, backend/Dockerfile, backend/requirements.txt, backend/requirements-dev.txt, backend/app/main.py, backend/app/core/config.py, backend/app/db/session.py, backend/app/api/health.py, backend/tests/conftest.py, backend/tests/test_health.py
**Try it:**
- `docker compose up --build`, then `curl localhost:8000/health` and `curl localhost:8000/health/db`.
- `docker compose run --rm tools pytest -v` runs the tests (since step 4a, in the tools container).
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

### Least privilege (database users)
**What:** give each program only the rights it needs. If someone breaks into the API, they get whatever the API's database login can do. If that login owns the tables, they can switch off the audit trigger and rewrite history. As `motie_app`, they can only do what the API itself does. So there are three logins with three jobs: the superuser creates logins, the owner changes the structure (migrations), and the app reads and writes rows.
**Here:** db/init/10-db-users.sh creates the users. docker-compose.yml gives the `api` container only `motie_app`'s password. backend/tests/core/test_db_privileges.py checks what `motie_app` can't do.
**Learn more:** [OWASP Database Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html)

### GRANT and table ownership
**What:** in Postgres, whoever creates a table owns it. Only the owner (or a superuser) can `ALTER` or `DROP` it or touch its triggers. Everyone else needs a `GRANT` for each action: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`. Postgres checks privileges *before* it runs triggers, so the app's `DELETE FROM core.audit_log` fails with "permission denied" and never reaches the trigger. The trigger is now a second wall, and it holds even against the owner.
**Here:** backend/alembic/versions/0007_app_privileges.py. Every future migration that adds a table must add its own `GRANT`. If one forgets, `test_every_table_is_owned_by_motie_owner_and_readable_by_the_app` names the table.
**Learn more:** [PostgreSQL docs: Privileges](https://www.postgresql.org/docs/16/ddl-priv.html)

### One-off containers (Compose profiles)
**What:** `docker compose run --rm tools <command>` starts a fresh container from the `tools` service, runs one command, then deletes the container (`--rm`). `profiles: ["tools"]` stops `docker compose up` from starting it. We use it for jobs that need the owner's password, so that password never sits in a server that runs all day.
**Here:** the `tools` service in docker-compose.yml.
**Learn more:** [Docker docs: docker compose run](https://docs.docker.com/reference/cli/docker/compose/run/), [Using profiles with Compose](https://docs.docker.com/compose/how-tos/profiles/)

### Positions vs roles
**What:** a *role* says what kind of user someone is: an applicant, Ministry staff, a system admin. A *position* is a post in the organisation chart, like "Director of Trade", that a person holds for a while and then hands over. Approvals belong to posts. When a new Director arrives, they take over the post, and every workflow that names the post works for them at once, without editing any workflow.
**Here:** `Role` and `Position` in backend/app/core/identity/models.py. `User.role_codes` and `User.position_codes` give each one as a set of codes.
**Learn more:** [Wikipedia: Role-based access control](https://en.wikipedia.org/wiki/Role-based_access_control). Our positions are close to what it calls roles; we keep "role" for the kind of user.

### Self-referencing foreign key
**What:** a column that points at another row of the *same* table. `positions.reports_to_id` holds the id of the post above, so the whole org chart (a tree) fits in one table. The top post has no boss, so its `reports_to_id` is empty. The danger is a loop (A reports to B, B reports to A), which would make "walk up the chain" run forever.
**Here:** `positions.reports_to_id` in backend/alembic/versions/0008_positions.py. The `positions_not_own_boss` check stops the shortest loop. `test_every_chain_of_command_ends_at_one_top_post` walks up from every post to catch longer ones.
**Learn more:** [PostgreSQL docs: recursive queries (WITH RECURSIVE)](https://www.postgresql.org/docs/16/queries-with.html#QUERIES-WITH-RECURSIVE), the usual way to walk such a tree in SQL.

### `ON CONFLICT DO NOTHING ... RETURNING`
**What:** "insert this row, unless one with the same key already exists; then tell me what you inserted". If nothing was inserted, nothing comes back. Checking first ("does the row exist?") and inserting second has a gap: two admins clicking at the same moment both see "no", and the second insert crashes. Doing it in one statement has no gap.
**Here:** `assign_position()` in backend/app/core/identity/service.py. It writes an audit row only when the insert returned something, so the log never records a change that didn't happen. `remove_position()` does the same with `DELETE ... RETURNING`.
**Learn more:** [PostgreSQL docs: INSERT ... ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT)

### Changing a column with existing data (expand, backfill, contract)
**What:** you can't swap one column for another in one go when rows already use it. Do it in three moves inside one migration. *Expand*: add the new column, allowing empty values. *Backfill*: fill it from the old column for every existing row. *Contract*: make it `NOT NULL`, then drop the old column. The `NOT NULL` step is also a safety check: if any row couldn't be converted, the migration fails and rolls back instead of leaving a move with no approver.
**Here:** backend/alembic/versions/0009_transitions_require_positions.py: `add_column` (expand), the `UPDATE ... FROM (VALUES ...)` (backfill), `alter_column(..., nullable=False)` and `drop_column` (contract). `downgrade()` does the same in reverse.
**Learn more:** [Martin Fowler: Parallel Change (expand and contract)](https://martinfowler.com/bliki/ParallelChange.html)

### Delegation (acting on behalf of)
**What:** letting someone use another person's authority for a limited time, while every action still records *who* acted and *whose* authority they used. In a ministry this is everyday work: "the PS, for the Minister". Three things make it safe: it's limited (dates, optionally one workflow), it's visible (both sides see it, and every use is logged) and it can be ended early (revoked).
**Here:** backend/app/core/workflow/delegation.py: `create_delegation()` checks the rules, and `active_delegations_to()` answers "which posts may this user act for today?". backend/app/core/workflow/service.py: `_permitted()` combines own posts and delegations, and `change_status()` writes `on_behalf_of` and `delegation_id` into the audit row.
**Learn more:** [Wikipedia: Delegation of authority](https://en.wikipedia.org/wiki/Delegation)

### Column-level privileges
**What:** a `GRANT` (see GRANT and table ownership) can name single columns: `GRANT UPDATE (revoked_at, revoked_by) ON core.delegations`. The app can then change those columns and nothing else in the row. Any `UPDATE` that touches another column fails with "permission denied". SQLAlchemy only sends the columns that actually changed, so ordinary code works.
**Here:** backend/alembic/versions/0010_delegations.py. Tested by the `stretch-delegation` case in backend/tests/core/test_db_privileges.py.
**Learn more:** [PostgreSQL docs: GRANT, column privileges](https://www.postgresql.org/docs/16/sql-grant.html)

### Testing with a fake "today" (monkeypatch)
**What:** code that asks "what's the date?" is hard to test: you can't wait until next week. So all delegation code gets the date from one function, `today()`. A test swaps that function for one returning any date it likes. pytest's `monkeypatch` fixture does the swap and puts the real function back when the test ends, even if it fails.
**Here:** `today()` in backend/app/core/workflow/delegation.py. `test_a_delegation_only_works_between_its_dates` in backend/tests/core/test_delegations.py moves "today" to the day before, the day after and the last day.
**Learn more:** [pytest docs: monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)

### NULL in unique constraints (`NULLS NOT DISTINCT`)
**What:** in SQL, `NULL` means "unknown", so two NULLs are never equal. Usually that's harmless, but it means a `UNIQUE (position_id, workflow_id, rank)` would let two general rules (workflow empty) share rank 1: Postgres doesn't see them as duplicates. Postgres 15 added `NULLS NOT DISTINCT`, which makes the constraint treat every NULL as the same value.
**Here:** `succession_orders_rank_key` and `succession_orders_successor_key` in backend/alembic/versions/0013_succession_orders.py. The `same-rank` case in backend/tests/core/test_succession.py only passes because of it.
**Learn more:** [PostgreSQL docs: Unique constraints](https://www.postgresql.org/docs/16/ddl-constraints.html#DDL-CONSTRAINTS-UNIQUE-CONSTRAINTS)

## 3. Decisions

### Confirmed by the Ministry

These were open questions; the Ministry has answered them. The code follows them and no longer marks them `[CONFIRM]`.

- **Chain of command (2026-10-19):** Minister → Permanent Secretary → Deputy PS.
- **ETLS route (2026-10-19):** Records → Minister → PS → Director of Industry and Investment. The Director signs the file and assigns it to an officer. See backend/alembic/versions/0012_confirmed_etls_route.py.
- **Who signs ETLS files (2026-10-19):** the Director of Industry and Investment.
- **"Assign" means minuting the file to an officer (2026-10-19).** It doesn't pass on the Director's signing power, so delegations still can't be passed on (step 4d).

### Choices made while building

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
| 2026-10-18 | Append-only enforced by a database trigger | only "be careful in Python"; `REVOKE UPDATE, DELETE` permissions | A trigger protects against every client, even the table owner. Since step 4a the app also has no `UPDATE`/`DELETE` rights on it, so there are two walls. |
| 2026-10-18 | One generic audit table (`entity_type` + `entity_id` + JSON `details`) | a separate history table per record type | Every module can log to it, and "show everything user X did" is one query. |
| 2026-10-18 | `record_event()` never commits | commit inside it | So a change and its audit row are always saved in the same transaction. |
| 2026-10-18 | Transitions name a required *role* for now | name a *position* (e.g. "Director of Trade") | CLAUDE.md says approvals attach to positions, with delegation for absences. Positions need their own tables. Until then, roles keep the engine working, and switching the column later is one migration. **Done in step 4c (migration 0009).** |
| 2026-10-18 | The PS gets the Minister's move as a second transition row | delegation | Placeholder for "PS when the Minister is away". With real delegation, the PS row goes and the Minister delegates when absent. **Done in step 4e (migration 0011).** |
| 2026-10-18 | One role may start a workflow (`workflows.start_role_id`) | a link table allowing several roles | Enough for ETLS. Becomes a table if Records also needs to open cases for walk-in applicants (see Open questions). |
| 2026-10-18 | The ETLS definition is seeded in the shared migration chain | a separate `etls` module migration | There's only one Alembic chain so far. When the `etls` schema arrives, its data can move with it. |
| 2026-10-18 | Database constraints guard the workflow's structure; tests guard its logic | everything in Python | Constraints (one initial status, statuses from the same workflow) protect against any client. Rules like "no dead ends" need a whole-graph check, which is easier as a test. |
| 2026-10-18 | The generic table is called `cases` | `files`, `requests`, `applications` | "File" collides with uploaded documents, which come later. "Application" is ETLS-specific. Module tables (e.g. `etls.applications`) will point at `core.cases.id`. |
| 2026-10-18 | The case's history lives only in `core.audit_log` | a separate `case_status_history` table | One source of truth. A second table could disagree with the audit log. |
| 2026-10-18 | Pessimistic locking (`FOR UPDATE`) | optimistic locking (a version number, retry on conflict) | Simpler to read, and contention is tiny (a handful of officers per file). No retry logic needed. |
| 2026-10-18 | 409 for "move not possible from here", 403 for "move exists but not for your role" | 400 for both | The frontend can show "this file has already moved on" (409) differently from "you can't do this" (403). |
| 2026-10-18 | Engine errors are Python exceptions, turned into HTTP codes in one handler | raise `HTTPException` inside the service | The service stays usable from the CLI, background jobs and tests, without knowing about HTTP. |
| 2026-10-18 | Applicants can't read the history | show applicants everything | History holds internal minutes and comments. Applicants see the current status only, until the Ministry decides otherwise. |
| 2026-10-19 | Three database users: the superuser only for setup, `motie_owner` for migrations, `motie_app` for the API | app connects as owner and we `REVOKE` some rights; migrations run as the superuser | The owner can always disable its own table's triggers, so the app must not be the owner. Migrations as the superuser would give migration code unlimited rights over the whole server; `motie_owner` can change our tables and nothing else. |
| 2026-10-19 | Database users created by a shell script in `docker-entrypoint-initdb.d`, safe to run again by hand | create them in a migration | Creating logins needs the superuser, and migrations deliberately don't have it. The passwords also stay in `.env`, out of committed files. |
| 2026-10-19 | Fixed user names (`motie_owner`, `motie_app`), passwords from `.env` | names set in `.env` too | Migration 0007 needs the name to `GRANT` to. One server runs one copy of the platform, so there's nothing to configure. |
| 2026-10-19 | Grants written out table by table in each migration | `ALTER DEFAULT PRIVILEGES` (new tables granted automatically) | Automatic grants fail *open*: a new append-only table would quietly get `DELETE`. Explicit grants fail *closed*: forget one and the API gets "permission denied", which a test catches straight away. |
| 2026-10-19 | The app gets no `DELETE` on users and cases, and only `SELECT` on roles and workflow definitions | read and write everything | These were already our rules ("users are deactivated, never deleted"; "workflows are loaded by migrations"). Now the database enforces them too. |
| 2026-10-19 | Migrations and tests run in a one-off `tools` container; the `api` container only has `motie_app`'s password | give the API container the owner's URL too, so `docker compose exec api alembic` keeps working | A dev Compose file tends to get copied to production. Keeping the owner's password out of the server that runs all day costs a few seconds per command. |
| 2026-10-19 | Tests run the code as `motie_app` | run tests as the owner | A missing grant then fails a test, not the Ministry server. The few tests that write workflow rows use `owner_session`. |
| 2026-10-19 | A database from before step 4a is handed over to `motie_owner` by the same script | wipe the volume and start again | No data is lost, and a Ministry server set up the old way would need the same handover. |
| 2026-10-19 | Roles stay, next to positions | turn roles into positions | Roles answer "what kind of user?" (applicant, staff, admin); positions answer "which post?". An applicant holds no post. |
| 2026-10-19 | A post can have several holders; a user can hold several posts | exactly one holder per post | There are several Trade Officers, and an officer may act as Director while keeping their own post. Whether top posts must have a single holder is an open question. |
| 2026-10-19 | When someone leaves a post, their holder row is deleted; the history is in the audit log | keep rows with start and end dates | One source of history, the same choice as for cases (step 3c). |
| 2026-10-19 | The org chart is loaded by migrations; the app may only read it (and change who holds posts) | an admin screen to edit the chart | Same rule as workflows. Changes to the chart are rare, and they then go through review like code. |
| 2026-10-19 | Positions live in the identity module, next to `User` | a separate `org` module | `User.positions` needs the `Position` class; two modules importing each other would be a circular import. Split it out if it grows. |
| 2026-10-19 | `Position` has no `department` or `reports_to` relationship objects, only the id columns | `lazy="selectin"` relationships | Positions are loaded with every user, on every request. Eager relationships would add a query per level of the chain each time. |
| 2026-10-19 | Reports-to loops are caught by a test, not a database trigger | a trigger running a recursive query on every change | Only migrations write the chart, and the tests check every migration. Add the trigger if an admin screen ever edits the chart. |
| 2026-10-19 | Posts are assigned with the CLI for now; the audit row has no actor | an admin API endpoint | Only someone with server access can assign posts, which suits a power this strong. An admin screen can come later. |
| 2026-10-19 | Old transitions converted by a fixed role-to-post mapping in migration 0009 | re-seed the ETLS workflow from scratch | Keeps the transition ids (and so the audit trail's meaning) unchanged. A role missing from the mapping makes the migration fail rather than drop a move. |
| 2026-10-19 | Who may *start* a workflow is still a role (`workflows.start_role_id`) | a position | Applicants hold no post. "Who may open a case" is about the kind of user, not a post. |
| 2026-10-19 | Seeing cases and history still depends on roles (`is_staff()`) | positions | Visibility rules aren't decided yet (see Open questions). Moves were the part CLAUDE.md said must follow posts. |
| 2026-10-19 | The audit key `as_role` became `as_position` | keep writing `as_role` | It says what was actually checked. Old rows keep `as_role`; the log is append-only, so code reading history must accept both. |
| 2026-10-19 | Delegation goes from post to post | from person to person | It matches "approvals attach to positions". If the PS changes while the Minister is away, the new PS can act at once. |
| 2026-10-19 | The delegating post keeps its own powers | suspend the delegator while delegated | If the Minister comes back early, they can act without first revoking. Both sides' actions are logged either way. |
| 2026-10-19 | Delegations aren't passed on (Minister → PS → Director doesn't let the Director act for the Minister) | follow chains | "Who could act for the Minister on 5 March?" stays one simple query, and nobody hands on powers they only borrowed. |
| 2026-10-19 | The engine finds the delegation by itself; own posts are tried first | the caller says "I'm acting for X" | Fewer ways to get it wrong. The button shows `on_behalf_of` before the click, and the audit row records it after. Using your own post first means the log shows the strongest basis for the action. |
| 2026-10-19 | Dates are whole days, both included, in UTC | start and end timestamps | People say "away from 3 to 10 March". The Gambia keeps GMT all year with no daylight saving, so the UTC date is the local date. |
| 2026-10-19 | No back-dating; at most 90 days `[CONFIRM]` | allow both | A back-dated delegation could make an earlier action look authorised. A delegation with no limit would hand a post's powers over for good. |
| 2026-10-19 | Revoke, never delete or edit; enforced by a column-level grant | let the app update or delete delegations | Audit rows point at `delegation_id`, so the delegation must stay as it was when it was used. |
| 2026-10-19 | If several delegations cover the same post, the oldest is recorded | the newest; refuse overlaps | Any of them gives the same right. Refusing overlaps would block a sensible fix ("I set the wrong end date, here's a second one"). |
| 2026-10-19 | Errors moved to `errors.py`; `service.py` still re-exports them | keep them in `service.py` | `delegation.py` needs them and `service.py` needs `delegation.py`. Importing each other would be a circular import. |
| 2026-10-19 | `available_actions` always includes `on_behalf_of` (`null` for your own moves) | leave it out when empty | A fixed shape is easier for the frontend. One existing test assertion gained `"on_behalf_of": None`. |
| 2026-10-19 | The PS placeholder row is deleted by a new migration (0011) | edit migration 0005 so the row was never seeded | Databases that already ran 0005 (yours, and any server) would never lose the row. Migrations that have run are never edited. |
| 2026-10-19 | The Minister records each absence as a delegation | a standing Minister → PS delegation with no end date | A standing delegation would recreate the placeholder under another name. A dated one shows *when* the PS was entitled to act. |
| 2026-10-19 | "With the Directorate" renamed to `with_director` in place | delete it and add a new status | Cases point at the status id. Renaming keeps every existing case valid; deleting would fail, or strand them. |
| 2026-10-19 | The Trade posts stay in the org chart; ETLS moves to the Industry and Investment posts | delete the Trade posts | The Directorate of Trade exists and will have its own work. Deleting posts loses the audit trail's meaning for anyone who held them. |
| 2026-10-19 | The officer's moves (approve, reject, return) are kept as they were | remove them, or make the Director's signature final | Without them, a case could never finish (the well-formedness test would fail). What the officer really does after signing is still an open question. |
| 2026-10-19 | The DPS gets the `director` role in tests | add a `deputy_permanent_secretary` role | Roles only say "staff or applicant" now; the post is what counts. A new role waits for the role list question. |
| 2026-10-19 | A test pins the whole ETLS route, row by row | only count the rows | The route is confirmed now. Any later change to it should be deliberate and show up as a failing test. |
| 2026-10-19 | Succession is its own table, not a kind of delegation | standing delegations with no end date | A delegation is a person's choice for their own absence; succession is the Ministry's rule. Keeping them apart lets the audit log say which one was used, and lets the engine give delegations priority. |
| 2026-10-19 | One line of succession per post, with ranks; no following of chains | look up each successor's own successor | The confirmed rule lists the whole chain (Minister → PS → DPS), so one list says it all and is easy to read. |
| 2026-10-19 | A workflow-specific line replaces the post's general line for that workflow | add the two together | "For ETLS the Director is covered by DPS Admin & Finance" is a complete answer. Adding lists together would make the order hard to predict. |
| 2026-10-19 | The PS's line (PS → DPS) is seeded too | seed only the Minister's line | It follows from the confirmed general chain. Without it, files would stop at "With the PS" whenever the PS is away. |
| 2026-10-19 | Succession rules are loaded by migrations; the app only reads them | an admin screen | Same rule as workflows and the org chart: rare changes, reviewed like code. |

## 4. Open questions

Items marked `[CONFIRM]` in the code, to check with the Ministry.

- [ ] **Role list:** is `applicant, records_officer, minister, permanent_secretary, director, officer, admin` right? Are there other roles (e.g. Deputy PS, Registrar)? See backend/alembic/versions/0002_roles_and_users.py.
- [ ] **Staff password policy:** does the Government of The Gambia have an ICT policy we must follow (length, expiry, two-factor)?
- [ ] **Session length:** is 60 minutes before re-login acceptable for officers? (`ACCESS_TOKEN_MINUTES` in settings.)
- [ ] **Security to-do before going live (not a Ministry question):** rate-limit `/auth/login` against password guessing, and serve the API only over HTTPS. Tokens sent over plain HTTP can be stolen.
- [ ] **Rest of the org chart:** the chain Minister → PS → DPS is confirmed. Still to check: the exact titles of the DPS and the ETLS officer post, which department the DPS sits in, whether there are other DPS posts, and where the Registry and the Directorate of Trade fit. See 0008 and 0012 in backend/alembic/versions/.
- [ ] **Single-holder posts:** should the database refuse a second Minister, PS or Director at the same time? Right now any post can have several holders.
- [ ] **Who may assign posts:** right now only someone with server access, through the CLI. Should an HR or admin officer do it from a screen?
- [ ] **Who may record a delegation:** only the post holder, or also e.g. the Minister's private secretary or a system admin on their behalf? See `create_delegation()` in backend/app/core/workflow/delegation.py.
- [ ] **Delegation limits:** is 90 days the right maximum (`MAX_DELEGATION_DAYS`)? Is back-dating ever needed, e.g. after an emergency?
- [ ] **Delegation rules:** should a delegation be passed on (PS → Director when both are away)? Should the delegating post be blocked while it is delegated?
- [ ] **The PS acting for the Minister:** confirm the PS may make *every* Minister's move during an absence (that's what an unscoped delegation allows), or only some, e.g. ETLS only (`"workflow": "etls_application"`).
- [ ] **Which DPS covers the Minister's step when both the Minister and the PS are away?** Placeholder: DPS Administration and Finance, the only DPS post we know of. See backend/alembic/versions/0013_succession_orders.py.
- [ ] **The PS's own line:** we assumed the general chain means DPS Admin & Finance also covers the PS. Confirm.
- [ ] **Audit retention:** how long must audit records be kept under Gambian public records rules?
- [ ] **ETLS after the Director signs:** what does the officer do with the file (issue the certificate, notify the applicant)? Who may reject an application, and at which step? Are there steps such as "returned to applicant for more documents", a fee payment or an inspection? See the officer's moves in backend/alembic/versions/0012_confirmed_etls_route.py.
- [ ] **Who may open an ETLS case:** only the applicant online, or can Records register walk-in applications too?
- [ ] **Who may see a case:** right now, any staff member sees every case. Should staff see only cases in their directorate, or only cases assigned to them? See `can_view()` in backend/app/core/workflow/service.py.
- [ ] **What applicants see:** only the current status, or also the steps taken (without internal comments)? See `case_history()` in backend/app/core/workflow/router.py.
- [ ] **Deadlines:** how many days may a file sit at each step before it's overdue? (Needed for deadline tracking, not built yet.)

## 5. Check yourself

Questions per step. Try to answer before reading the answers.

### Step 5b
1. The Ministry adds a rule: for ETLS only, the Minister is covered by the DPS straight away. Which rows does `succession_order()` return for the Minister on an ETLS case, and on a case of another workflow?
2. Without `NULLS NOT DISTINCT`, what mistake could a migration make without the database noticing?
3. Why is the PS → DPS row in the seed, when the Ministry only spelled out the Minister's chain and the Director's ETLS rule?

#### Show answers
1. On ETLS: only the DPS, because the ETLS rows *replace* the Minister's general line. On any other workflow: the general line, PS then DPS. `test_a_workflow_rule_replaces_the_general_one` checks exactly this.
2. Insert two general rules for the same post with the same rank (or the same successor). Two NULLs are never equal, so the unique constraint wouldn't fire, and the order between the two rows would be a coin toss.
3. The confirmed general chain is Minister → PS → DPS, so we read it as "the DPS covers the PS" too. Without it, files would stop at "With the PS" whenever the PS is away. It's listed under Open questions so the Ministry can confirm.

### Step 5a
1. A case was "With the Directorate" when you ran migration 0012. Where is it afterwards, and why didn't the migration need to touch `core.cases`?
2. Why does the ETLS workflow still have an officer "Approve" move, when the Director now signs?
3. Why does the race test need `release_posts`, when other tests don't clean up after themselves?

#### Show answers
1. It's "With the Director of Industry and Investment". The case points at the status *id*, and 0012 renamed that status row (`code` and `name`) without changing its id. The next move is then the Director of Industry's "Sign and assign to an officer".
2. Because the Ministry hasn't said yet what the officer does after the signature, or who may reject. Removing the officer's moves would leave "With the officer" as a dead end, which `test_every_workflow_is_well_formed` refuses. It's an open question.
3. Other tests run inside a transaction that is rolled back (`db_session`). The race test commits for real on separate connections, so its post holders would stay for the rest of the run. Once absences matter (step 5d), a leftover Minister who isn't absent would make the Minister's post look present.

### Step 4e
1. The Minister is in Banjul (no delegation exists). The PS tries to minute an ETLS file to the Directorate. What happens? How would that answer have differed before step 4e?
2. Why did we write a new migration (0011) instead of deleting the PS line from migration 0005?
3. The Minister delegates to the PS for ETLS only. What does the audit row look like when the PS minutes a file?

#### Show answers
1. **403**, and `available_actions` is empty for the PS. Before 4e the PS had their own transition row for that move, so it would have succeeded at any time, with nothing in the log showing the Minister was away.
2. Migrations that have already run are never edited. Your dev database (and any server) ran 0005 and has the row. Alembic only runs migrations a database hasn't had yet, so an edited 0005 would never run there and the row would stay. A new migration removes it everywhere, and its `downgrade()` can put it back.
3. `"as_position": "permanent_secretary"`, `"on_behalf_of": "minister"`, `"delegation_id": <its id>`, together with `from`, `to`, `transition` and `comment` as before. `actor_user_id` is the PS's user id.

### Step 4d
1. The Director delegates to the Trade Officer post from 3 to 10 March. On 11 March a Trade Officer tries to assign a file. What happens, and which line decides it?
2. Why can the app set `revoked_at` on a delegation but not change `ends_on`? What could go wrong if it could?
3. The Director delegates to the Trade Officer post, and the Trade Officer post delegates to the Records Officer post. Can a Records Officer assign a file to an officer? Why?

#### Show answers
1. **403** "None of your positions can make this move." `active_delegations_to()` only returns delegations where `starts_on <= today` and `ends_on >= today`. On 11 March the delegation is no longer active, so `_permitted()` finds nothing.
2. Migration 0010 grants `UPDATE` on those two columns only. If `ends_on` could change, someone could later stretch a delegation to cover a move made after it ended, and the audit trail would look legitimate. Revoking only ever shortens a delegation, and it's logged.
3. No. `active_delegations_to()` only looks at delegations *to* posts the user holds. The Records Officer has one from the Trade Officer post, but the assign move needs the Director's post, and nothing delegates that to the Records Officer post. Delegations aren't passed on (`test_delegations_are_not_passed_on`).

### Step 4c
1. The Ministry decides that the PS, not the Minister, minutes ETLS files to the Directorate. What do you change?
2. A user has the `director` role but holds no post. They try to move a case from `with_directorate` to `with_officer`. What do they get, and which line decides it?
3. Why does migration 0009 add `required_position_id` as nullable first and only make it `NOT NULL` after the `UPDATE`?

#### Show answers
1. A new migration that updates (or deletes) the `with_minister` → `with_directorate` row for the `minister` post. No Python changes, and no change to who holds which post.
2. **403** "None of your positions can make this move." In `change_status()`, `held` is empty, so `next(...)` finds no matching move and raises `NotPermitted`. Roles no longer grant moves.
3. Existing rows have no value for the new column when it's added, so `NOT NULL` would fail straight away. The `UPDATE` fills it in from the old role. Then `NOT NULL` both locks the rule in and checks that every row was converted: if one wasn't, the migration fails and rolls back.

### Step 4b
1. A new Director of Trade replaces the old one. What changes in the database, and what stays the same?
2. Why does `assign_position()` use `ON CONFLICT DO NOTHING ... RETURNING` instead of first checking whether the user already holds the post?
3. Why does `Position` have a `reports_to_id` column but no `reports_to` relationship?

#### Show answers
1. One row in `core.position_holders` is deleted (old Director) and one is inserted (new Director), and each change adds an audit row. The positions table and, from step 4c, the workflow transitions stay the same, because they name the *post*, not the person.
2. Check-then-insert has a gap: two admins at the same moment both see "not held", and the second insert fails on the primary key. A single statement has no gap. And since nothing comes back when the row already existed, no audit row is written for a change that didn't happen.
3. Positions are loaded with every user on every request (`User.positions` is `selectin`). A self-referencing relationship would also load each boss, then each boss's boss, adding queries to every request. The id is enough; code that needs the chain can look it up.

### Step 4a
1. Someone takes full control of the API process and runs `ALTER TABLE core.audit_log DISABLE TRIGGER ALL`. What happens, and why? What about `DELETE FROM core.audit_log`?
2. You write migration `0012` that creates `core.documents` and forget the `GRANT`. What breaks, and what tells you?
3. Why does `docker compose exec api alembic upgrade head` no longer work, and why is that good?

#### Show answers
1. `ERROR: must be owner of table audit_log`. The API logs in as `motie_app`, and only a table's owner (`motie_owner`) or a superuser may alter it or its triggers. The `DELETE` gives `permission denied`: `motie_app` was never granted `DELETE` on that table (see 0007), and Postgres checks that before the trigger even runs.
2. The API gets "permission denied for table documents" the first time it touches the table, so it fails closed, never open. `test_every_table_is_owned_by_motie_owner_and_readable_by_the_app` fails and names `core.documents`. Any test using the table through `db_session` fails too, because tests run as `motie_app`.
3. The `api` container has no `MIGRATION_DATABASE_URL`, so `get_url()` in backend/alembic/env.py stops with a clear message. That's good: the server that runs all day, and could be attacked, never holds the password that can change tables. Use `docker compose run --rm tools alembic upgrade head`.

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
1. Something else: a new migration that inserts one row into `core.workflow_transitions` (`with_directorate` → `rejected`, position `director_of_trade` since step 4c). No Python changes, because workflows are data.
2. So a transition can only point to a status in its *own* workflow. With `to_status_id` alone, a move could lead into another process's status, and a case would end up stuck in a workflow it doesn't belong to.
3. The `JOIN` on the status code finds no match, so that row is silently left out. `test_etls_workflow_is_seeded` expects exactly 7 transitions and fails. `test_every_workflow_is_well_formed` would probably also report a dead end.

### Step 3a
1. Why doesn't `record_event()` call `session.commit()`?
2. Someone with psql access runs `UPDATE core.audit_log SET actor_user_id = 3 WHERE id = 10`. What happens? Is there still a way around it?
3. Why is `entity_id` a text column and not a number?

#### Show answers
1. So the change and its audit row are committed together, in one transaction. If `record_event()` committed on its own, a crash between the two commits could leave an audit row for a change that never happened, or a change with no audit row.
2. The trigger `audit_log_no_update_delete` raises an error and the update is cancelled. The way around it is that the table owner or a superuser can disable the trigger. That's why, since step 4a, the app connects as `motie_app`, which is neither.
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
1. `docker compose run --rm tools alembic upgrade head`. It reads `alembic_version` (0002) and runs only `0003`.
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
