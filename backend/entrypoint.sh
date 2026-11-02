#!/bin/bash
set -e

# Migrations run on EVERY replica start. With >1 backend replica booting at
# the same time, concurrent `alembic upgrade` can race (duplicate DDL,
# version-table conflicts). pg_advisory_lock is session-scoped, so one Python
# holder process takes the cluster-wide lock and runs the migration commands
# as subprocesses; the lock releases on exit. Stop-gap until migrations move
# to a one-shot deploy job (see docs/SCALING.md).
#
# The lock connection uses MIGRATION_DATABASE_URL (direct to Postgres), not the
# pooled DATABASE_URL: through a transaction-mode pooler the lock and the unlock
# can land on different server connections, leaving a lock nobody holds.
#
# `db doctor` runs first, inside the lock. It compares every module's version
# table against its migration chain and refuses the boot on drift, so a broken
# state produces one readable error instead of an endless restart loop under
# `restart: unless-stopped`. An empty database is not drift — a fresh install
# passes.
python - <<'EOF'
import subprocess
import sys

import psycopg2

from app.cli._migration_lock import (
    MIGRATION_LOCK_APPLICATION_NAME,
    MIGRATION_LOCK_KEY,
)
from app.config import settings

dsn = settings.migration_database_url.replace('postgresql+psycopg2://', 'postgresql://')
# The name is not decoration: a database rebuild holds the same lock and its
# sweep spares the sessions that carry this name (app/cli/_reset_sweep.py), so
# a backend waiting here is not killed and restarted into a second migration
# pass.
conn = psycopg2.connect(dsn, application_name=MIGRATION_LOCK_APPLICATION_NAME)
conn.autocommit = True
cur = conn.cursor()
print('Waiting for migration advisory lock...', flush=True)
cur.execute('SELECT pg_advisory_lock(%s)', (MIGRATION_LOCK_KEY,))
try:
    for label, cmd in (
        ('pre-flight check', ['python', 'manage.py', 'db', 'doctor']),
        ('core migrations', ['alembic', 'upgrade', 'heads']),
        ('module migrations', ['python', 'manage.py', 'db', 'upgrade-modules']),
    ):
        print(f"Running {label}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            if label == 'pre-flight check':
                # The doctor prints its own finding and the fix for it; this
                # line must not guess which one it was. A module rejected at
                # discovery does not fail the check, but a package that breaks
                # the doctor in some other way does, and then the way back is
                # the one command that works while the container restarts.
                print(
                    'Pre-flight check failed: what it found is printed above. '
                    'Refusing to migrate until it passes. If a module installed '
                    'or upgraded just now is the cause, take it out with '
                    "'docker compose run --rm --no-deps -T --entrypoint uv "
                    "backend run python manage.py module uninstall <name>' "
                    '(MODULES_GUIDE.md, "When the backend does not come back").',
                    flush=True,
                )
            sys.exit(result.returncode)
finally:
    cur.execute('SELECT pg_advisory_unlock(%s)', (MIGRATION_LOCK_KEY,))
    cur.close()
    conn.close()
EOF

# Start application
echo "Starting application..."
exec "$@"
