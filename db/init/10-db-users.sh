#!/bin/bash
# Creates the two database users the platform runs with:
#
#   motie_owner  owns the database and every table in it. Only migrations and
#                admin tools log in as this user.
#   motie_app    what the API logs in as. It can read and write rows it has been
#                granted (see alembic/versions/0007_app_privileges.py), but it
#                owns nothing, so it can't ALTER, DROP or disable triggers.
#
# POSTGRES_USER (the superuser the image creates) is only for this script and for
# creating the test database. Nothing else should log in with it.
#
# Postgres runs this automatically the first time the db container starts on an
# empty volume. It is safe to run again on an existing database, e.g. to apply a
# password changed in .env, or to hand over a database created before step 4a:
#     docker compose exec db bash /docker-entrypoint-initdb.d/10-db-users.sh
set -euo pipefail

: "${MIGRATION_DB_PASSWORD:?Set MIGRATION_DB_PASSWORD in .env}"
: "${APP_DB_PASSWORD:?Set APP_DB_PASSWORD in .env}"

# Passwords go in as psql variables (:'name' quotes them safely), never pasted
# into the SQL text, so a quote in a password can't break or change the SQL.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v db="$POSTGRES_DB" \
    -v owner_password="$MIGRATION_DB_PASSWORD" \
    -v app_password="$APP_DB_PASSWORD" <<'SQL'
-- Postgres has no "CREATE ROLE IF NOT EXISTS". \gexec runs each row a query
-- returns as a statement, so these only create the role when it's missing.
SELECT 'CREATE ROLE motie_owner' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'motie_owner') \gexec
SELECT 'CREATE ROLE motie_app' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'motie_app') \gexec

-- Set every attribute explicitly, so re-running fixes a role someone changed by hand.
ALTER ROLE motie_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_password';
ALTER ROLE motie_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_password';

-- The database owner may create schemas, and (Postgres 15+) tables in "public",
-- where Alembic keeps its alembic_version table.
ALTER DATABASE :"db" OWNER TO motie_owner;

-- Hand over anything created before these users existed (a database from before
-- step 4a, where migrations ran as the superuser). On a new volume this finds nothing.
DO $$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT nspname FROM pg_namespace
        WHERE nspname NOT IN ('public', 'information_schema') AND nspname NOT LIKE 'pg\_%'
    LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO motie_owner', obj.nspname);
    END LOOP;

    -- Moving a table also moves its indexes, triggers and identity sequences.
    FOR obj IN
        SELECT schemaname, tablename FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    LOOP
        EXECUTE format('ALTER TABLE %I.%I OWNER TO motie_owner', obj.schemaname, obj.tablename);
    END LOOP;

    FOR obj IN
        SELECT p.oid::regprocedure AS fn
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('public', 'information_schema') AND n.nspname NOT LIKE 'pg\_%'
    LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO motie_owner', obj.fn);
    END LOOP;
END
$$;
SQL

echo "Database users motie_owner and motie_app are ready."
