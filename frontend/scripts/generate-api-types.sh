#!/usr/bin/env bash
# Generate TypeScript types from the backend OpenAPI schema.
#
# The schema comes from one of two places:
#   * a file, when OPENAPI_FILE is set — used by `make check-api-types`, which
#     dumps it straight out of the backend container. A dev/prod backend runs
#     with DEBUG=false and serves no /openapi.json, so the HTTP route below is
#     not available where the gate needs to run.
#   * the running backend over HTTP otherwise — used by CI, which starts a
#     backend with DEBUG=true anyway.
#
# Usage:
#   ./scripts/generate-api-types.sh                  # fetch from localhost:8005
#   ./scripts/generate-api-types.sh --check          # fail if the types are stale
#   BACKEND_URL=http://host:port ./scripts/generate-api-types.sh
#   OPENAPI_FILE=/tmp/openapi.json ./scripts/generate-api-types.sh --check

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8005}"
OPENAPI_URL="${BACKEND_URL}/openapi.json"
OPENAPI_FILE="${OPENAPI_FILE:-}"
OUT_FILE="src/types/api-generated.ts"
ROUTES_FILE="src/types/api-routes.ts"

# Parse flags
CHECK_MODE=false
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_MODE=true ;;
  esac
done

if [ -n "$OPENAPI_FILE" ]; then
  # Before the pipeline: `cat` on a missing dump dies inside
  # `read_schema | node -e …` under `set -euo pipefail`, and the reader gets
  # a JSON syntax error that reads as contract drift in their own diff. The
  # missing thing is the dump, so the missing-dump message comes first.
  if [ ! -s "$OPENAPI_FILE" ]; then
    echo "ERROR: no OpenAPI schema dump at ${OPENAPI_FILE} — the file does not exist or is empty." >&2
    echo "  The dump is written by 'make generate-api-types' / 'make check-api-types'," >&2
    echo "  which read it straight out of the backend container (a backend with" >&2
    echo "  DEBUG=false serves no /openapi.json to fetch)." >&2
    exit 1
  fi
  SCHEMA_SOURCE="$OPENAPI_FILE"
  echo "Reading OpenAPI schema from ${OPENAPI_FILE}..."
else
  SCHEMA_SOURCE="$OPENAPI_URL"
  echo "Fetching OpenAPI schema from ${OPENAPI_URL}..."
fi

# Canonicalise before generating. openapi-typescript emits keys in schema order,
# and the backend registers module routers in an order that depends on what it
# managed to import, so two hosts serving the *identical* API produce
# byte-different files — which reads as contract drift and blocks CI forever.
# Sorting paths and schemas makes the artefact a function of the API alone.
# The second stage drops server defaults from request-only schemas, so a field
# the caller may omit is generated optional (scripts/openapi-request-defaults.mjs).
SCHEMA_FILE="$(mktemp -t openapi.XXXXXX.json)"
TMP_TYPES="$(mktemp -t api-generated.XXXXXX.ts)"
trap 'rm -f "$SCHEMA_FILE" "$TMP_TYPES"' EXIT

read_schema() {
  if [ -n "$OPENAPI_FILE" ]; then
    cat "$OPENAPI_FILE"
  else
    curl -sf "$OPENAPI_URL"
  fi
}

read_schema | node -e "
  const fs = require('fs');
  const schema = JSON.parse(fs.readFileSync('/dev/stdin', 'utf8'));
  const sortKeys = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
  if (schema.paths) schema.paths = sortKeys(schema.paths);
  if (schema.components?.schemas) schema.components.schemas = sortKeys(schema.components.schemas);
  process.stdout.write(JSON.stringify(schema));
" | node "$(dirname "${BASH_SOURCE[0]}")/openapi-request-defaults.mjs" > "$SCHEMA_FILE"

if [ ! -s "$SCHEMA_FILE" ]; then
  echo "ERROR: could not read a schema from ${SCHEMA_SOURCE}" >&2
  if [ -z "$OPENAPI_FILE" ]; then
    echo "  (a backend with DEBUG=false does not serve /openapi.json —" >&2
    echo "   use 'make check-api-types', which dumps it from the container)" >&2
  fi
  exit 1
fi

if [ "$CHECK_MODE" = true ]; then
  # `--check` only says yes or no. On CI that is useless: the backend there
  # serves a different schema than any developer's machine, so "stale" without
  # a diff sends you guessing. Generate to a temp file and show what moved.
  npx openapi-typescript "$SCHEMA_FILE" -o "$TMP_TYPES"

  if diff -q "$TMP_TYPES" "$OUT_FILE" >/dev/null 2>&1; then
    echo "OK: generated types are up-to-date."
    exit 0
  fi

  echo ""
  echo "ERROR: ${OUT_FILE} is stale. Regenerate with:"
  echo "  make generate-api-types"
  echo ""
  echo "--- routes the live schema has that the committed types lack (and vice versa) ---"
  node -e "
    const fs = require('fs');
    const live = Object.keys(JSON.parse(fs.readFileSync('$SCHEMA_FILE','utf8')).paths || {});
    const committed = (fs.readFileSync('${ROUTES_FILE}','utf8').match(/\"(\/[^\"]*)\"/g) || [])
      .map((s) => s.slice(1, -1));
    const l = new Set(live), c = new Set(committed);
    const only = (a, b) => [...a].filter((x) => !b.has(x)).sort();
    for (const p of only(l, c)) console.log('  + ' + p + '  (live only)');
    for (const p of only(c, l)) console.log('  - ' + p + '  (committed only)');
    if (l.size === c.size && only(l, c).length === 0) {
      console.log('  (route lists match — the drift is in schemas, not paths)');
    }
  " || echo "  (route comparison unavailable)"
  echo ""
  echo "--- first 40 lines of the type diff (committed vs live) ---"
  diff "$OUT_FILE" "$TMP_TYPES" | head -40 || true
  exit 1
else
  npx openapi-typescript "$SCHEMA_FILE" -o "$OUT_FILE"
  echo "Generated ${OUT_FILE}"

  # Extract route paths as a runtime array for smoke tests
  node -e "
    const fs = require('fs');
    const schema = JSON.parse(fs.readFileSync('$SCHEMA_FILE', 'utf8'));
    const routes = Object.keys(schema.paths || {}).sort();
    const content = [
      '/**',
      ' * Auto-generated list of API routes from backend OpenAPI schema.',
      ' * Used by contract smoke tests. Do not edit manually.',
      ' */',
      'export const API_ROUTES = ' + JSON.stringify(routes, null, 2) + ' as const;',
      '',
    ].join('\n');
    fs.writeFileSync('${ROUTES_FILE}', content);
    console.log('Generated ${ROUTES_FILE} (' + routes.length + ' routes)');
  "
fi
