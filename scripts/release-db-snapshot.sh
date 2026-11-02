#!/usr/bin/env bash
# make release-db-snapshot — freeze the database a release leaves on disk.
#
# Every installation made from a release has to upgrade to every later one.
# The migration tests start from an empty database, which no installation
# is: a backfill that assumes a column is empty, or a constraint added over
# rows that break it, passes there and fails on a database somebody used.
# So each release is cut with a snapshot of what it leaves behind — the
# schema the release's migrations built, with the rows the first run and the
# demo seed write — and
# tests/integration/test_a_released_database_upgrades_to_head.py upgrades
# every snapshot to head on every run.
#
# Run it on the release commit — the last migration of the release in, the
# tag not yet made, so the tag carries the snapshot — against a running
# development stack. The stack's own database is not touched: the seed goes
# into a scratch database beside it, which is dropped again once the dump is
# written.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
version="${VERSION:-$(sed -n 's/^version = "\(.*\)"$/\1/p' "$here/backend/pyproject.toml" | head -n 1)}"
[ -n "$version" ] || { echo "no version in backend/pyproject.toml" >&2; exit 1; }
out="$here/backend/tests/fixtures/release_databases/v$version.sql.gz"
scratch="release_snapshot"
# Enough rows that every seeded table holds some, few enough that the
# committed file stays around a hundred kilobytes.
items=40

commit="$(git -C "$here" rev-parse HEAD)"

psql_admin() {
    docker compose exec -T db psql -U inventari_user -d postgres -q -v ON_ERROR_STOP=1 -c "$1"
}

psql_admin "DROP DATABASE IF EXISTS $scratch"
psql_admin "CREATE DATABASE $scratch"
trap 'psql_admin "DROP DATABASE IF EXISTS $scratch" || true' EXIT

# The demo reset is the documented first run plus the demo rows: migrations,
# system data, the administrator, the onboarding answered, then the seed.
# The reset empties whatever storage and inbox it is configured with, so it
# gets ones of its own: a local directory instead of the stack's uploads or
# bucket, and no demo inbox at all.
docker compose exec -T -e INVENTARI_DEMO=true -e MIGRATION_DATABASE_URL= \
    -e FILE_STORAGE_BACKEND=local \
    -e FILE_STORAGE_LOCAL_PATH=/tmp/release-snapshot-uploads \
    -e DEMO_INBOX_API_URL= backend \
    sh -c "DATABASE_URL=\"\${DATABASE_URL%/*}/$scratch\" \
        uv run python manage.py demo reset --items $items \
        && rm -rf /tmp/release-snapshot-uploads"

# Plain SQL with one INSERT per row, so the test restores it through the
# database driver alone: the backend image has no psql. pg_dump 17 wraps the
# script in psql-only \restrict lines, which a driver cannot run.
mkdir -p "$(dirname "$out")"
{
    echo "-- Inventari v$version: the database the release leaves on disk."
    echo "-- Cut by scripts/release-db-snapshot.sh from $commit."
    docker compose exec -T db pg_dump -U inventari_user -d "$scratch" \
        --no-owner --no-privileges --column-inserts | grep -v '^\\'
} | gzip -9 -n > "$out"

echo "Wrote $out ($(wc -c < "$out") bytes)."
