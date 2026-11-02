"""The one statement a reset runs before it drops the schema.

Two commands empty the database first — ``db reset`` and the nightly demo
rebuild — and each carried its own copy of the same statement. They asked Postgres to terminate *every* session in the
database, which is one word away from a command that cannot run.

The application connects as a role without SUPERUSER
(``docker/postgres/app-role.sh``), and Postgres refuses a non-superuser the
right to terminate a superuser's process. On a stack where the app role
shares the database with the 02:00 ``pg_dump`` or an operator's ``psql``,
the sweep therefore raises ``permission denied to terminate process`` and the
reset stops before ``DROP SCHEMA`` — the demo keeps yesterday's data and the
rebuild reports a failure nobody is watching for.

``usename = current_user`` is the whole answer. A reset has to clear the
sessions of its own role — those are the ones holding the schema it is about
to drop — and a session this role may not terminate is by definition not one
it needs.

One session of that role is also not one it needs, and distinguishing it is
the second half: a backend waiting for the migration advisory lock
(``app.cli._migration_lock``) holds no schema yet. Ending it makes the
entrypoint exit non-zero and ``restart: unless-stopped`` starts it again, so
the rollback this sweep begins looks like a failed deploy and the migrations
run twice. The caller holds that lock across the rebuild, so the session the
name spares is waiting, never mid-DDL.
"""

from __future__ import annotations

from app.cli._migration_lock import MIGRATION_LOCK_APPLICATION_NAME

#: Every other session of this role in this database, except one waiting for
#: the migration lock. Written once so the predicate that keeps a
#: non-superuser inside what it may do cannot drift back out of one of the
#: call sites.
TERMINATE_OTHER_SESSIONS_SQL = (
    'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
    'WHERE datname = current_database() '
    'AND pid <> pg_backend_pid() '
    'AND usename = current_user '
    'AND application_name IS DISTINCT FROM :migration_app_name'
)

#: The bind value the statement above needs: the one session name it spares.
TERMINATE_OTHER_SESSIONS_PARAMS = {
    'migration_app_name': MIGRATION_LOCK_APPLICATION_NAME,
}
