#!/usr/bin/env bash
# Creates the k6 load-test users, writes load_tests/users.csv and seeds the
# organisations with items. Run it once before the first k6 run.
#
#   K6_PASSWORD='MySecret123!' make loadtest-seed
#
# Env: K6_PASSWORD (required), USER_COUNT (default 100), SEED_ARGS (extra
# arguments for seed_load_test_data.py), PYRUN (command that runs Python in the
# backend directory; default: inside the compose backend container).
set -euo pipefail

: "${K6_PASSWORD:?Set K6_PASSWORD to the shared password for the load-test users}"
root="$(cd "$(dirname "$0")/.." && pwd)"
count="${USER_COUNT:-100}"
export K6_PASSWORD

if [ -z "${PYRUN:-}" ]; then
  cd "$root"
  PYRUN="docker compose exec -T -e K6_PASSWORD backend uv run python"
else
  cd "$root/backend"
fi

# The CSV goes through stdout so it lands on the host, not inside the container.
# Write to a temp file first: a failed seed must not leave an empty users.csv.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
$PYRUN seed_load_test_users.py --count "$count" --stdout > "$tmp"
test -s "$tmp"
# mktemp creates the file readable by its owner only, and the k6 container runs as
# another user (UID 12345) that reads users.csv through a bind mount. The
# passwords in it are the shared fixture password, nothing to guard.
chmod 644 "$tmp"
mkdir -p "$root/load_tests"
mv "$tmp" "$root/load_tests/users.csv"
trap - EXIT

# shellcheck disable=SC2086
# Best effort, as it always was in CI: users.csv is already in place, and a random
# barcode collision in the item seeder must not discard it.
$PYRUN seed_load_test_data.py ${SEED_ARGS:-} \
  || echo "WARNING: seed_load_test_data.py failed; users.csv is written, items are partial" >&2
