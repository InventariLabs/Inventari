#!/bin/sh
# The application's database role: the owner of the schema, not a superuser.
#
# The postgres image makes POSTGRES_USER the bootstrap superuser, and that
# role can never lose SUPERUSER ("The bootstrap superuser must have the
# SUPERUSER attribute"). Running the application under it meant any SQL
# injection ran with COPY ... TO PROGRAM and pg_read_file at hand. So the
# bootstrap role stays the administrator — this script, backups, restores —
# and the application connects as DB_APP_USER: LOGIN, NOSUPERUSER, NOCREATEDB,
# NOCREATEROLE, owner of the database and of everything in its public schema.
# Owning is what migrations need, including the ones a module runs when it is
# installed from the running application, and CREATE EXTENSION pg_trgm (a
# trusted extension, allowed to the database owner).
#
# Runs on every start of the stack, before PgBouncer and the backend, and is
# idempotent:
#   - creates the role when it is missing and (re)sets its attributes and
#     password, so changing DB_APP_PASSWORD in .env takes effect on the next up;
#   - hands the database, the public schema and every object in it that the
#     role does not own yet over to it. On a fresh install that is nothing; on
#     an existing one it moves what the old superuser owned. Objects that
#     belong to an extension stay with the extension. REASSIGN OWNED cannot do
#     this: Postgres refuses it for the bootstrap superuser.
set -eu

: "${PGHOST:?required}"
: "${PGUSER:?required — the bootstrap superuser (DB_USER)}"
: "${PGPASSWORD:?required}"
: "${PGDATABASE:?required}"
: "${DB_APP_USER:?required}"
: "${DB_APP_PASSWORD:?required — set DB_APP_PASSWORD in .env (PRODUCTS_DB_APP_PASSWORD for the products database)}"

if [ "$DB_APP_USER" = "$PGUSER" ]; then
    echo "app-role: DB_APP_USER must differ from DB_USER ($PGUSER) — the application role is the one without SUPERUSER" >&2
    exit 1
fi

until pg_isready -q; do sleep 1; done

psql -X -q -v ON_ERROR_STOP=1 -v app="$DB_APP_USER" -v pw="$DB_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I', :'app')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app') \gexec

ALTER ROLE :"app" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'pw';

SELECT format('ALTER DATABASE %I OWNER TO %I', current_database(), :'app') \gexec
ALTER SCHEMA public OWNER TO :"app";

-- Tables first: a table takes its indexes and the sequences behind its serial
-- and identity columns along, which refuse to be moved on their own.
SELECT format(
    'ALTER %s %s OWNER TO %I',
    CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
    c.oid::regclass, :'app')
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND pg_get_userbyid(c.relowner) <> :'app'
  AND NOT EXISTS (SELECT FROM pg_depend d
                  WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e') \gexec

SELECT format('ALTER SEQUENCE %s OWNER TO %I', c.oid::regclass, :'app')
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace
  AND c.relkind = 'S'
  AND pg_get_userbyid(c.relowner) <> :'app'
  AND NOT EXISTS (SELECT FROM pg_depend d
                  WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e') \gexec

SELECT format('ALTER %s %s OWNER TO %I',
              CASE p.prokind WHEN 'a' THEN 'AGGREGATE' ELSE 'ROUTINE' END, p.oid::regprocedure, :'app')
FROM pg_proc p
WHERE p.pronamespace = 'public'::regnamespace
  AND pg_get_userbyid(p.proowner) <> :'app'
  AND NOT EXISTS (SELECT FROM pg_depend d
                  WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e') \gexec

-- Enums, domains, ranges and free-standing composite types. Array types, the
-- row type of a table and a range's multirange follow their owner.
SELECT format('ALTER %s %s OWNER TO %I',
              CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END, t.oid::regtype, :'app')
FROM pg_type t
WHERE t.typnamespace = 'public'::regnamespace
  AND pg_get_userbyid(t.typowner) <> :'app'
  AND t.typcategory <> 'A'
  AND t.typtype <> 'm'
  AND (t.typrelid = 0 OR (SELECT c.relkind FROM pg_class c WHERE c.oid = t.typrelid) = 'c')
  AND NOT EXISTS (SELECT FROM pg_depend d
                  WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e') \gexec

SELECT format('app-role: %s — superuser %s, owns %s of %s relations in public',
              r.rolname, CASE WHEN r.rolsuper THEN 'true' ELSE 'false' END,
              count(c.oid) FILTER (WHERE c.relowner = r.oid), count(c.oid))
FROM pg_roles r
LEFT JOIN pg_class c ON c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
WHERE r.rolname = :'app'
GROUP BY r.rolname, r.rolsuper \g (format=unaligned tuples_only)
SQL
