# Load & E2E Tests — Inventari

## Structure

```
load_tests/                  ← k6 (load tests)
  scenarios/
    auth.js                  ← login helper
    browse_and_scan.js       ← typical user scenario (read-heavy)
    write_operations.js      ← write-heavy scenario (adding items)
    spike_test.js            ← sudden traffic burst
  grafana/provisioning/      ← Grafana auto-configuration
  prepare.sh                 ← creates the k6 users and seeds items (make loadtest-seed)
  scale/measure.py           ← warehouse-scale measurement (see below); results in scale/results/
docker-compose.loadtest.yml  ← k6 + InfluxDB + Grafana
docker-compose.loadtest-backend.yml ← production-like backend (gunicorn, 4 workers) for a run
docker-compose.scale.yml     ← production's database settings for the warehouse-scale run

frontend/tests/e2e/          ← Playwright E2E (UI tests)
  *.spec.ts                  ← auth, items, scan, documents, equipment, ...
frontend/playwright.config.ts ← Playwright config (baseURL, webServer, reporters)
```

---

## k6 — load tests

### Requirements
- Docker + Docker Compose

### Visualisation stack (one-time setup)
```bash
docker compose -f docker-compose.loadtest.yml up influxdb grafana -d
```
Grafana: http://localhost:3001 (no login required)
Import dashboard: **Grafana → Dashboards → Import → enter ID: `2587`**

### Prepare test data (REQUIRED)

Tests must run against a realistic database — an empty database gives misleading performance numbers.

**Run the preparation step (creates the users, writes `load_tests/users.csv`, seeds items):**
```bash
# LOAD_TESTING=true disables the global rate limiter (see backend/app/core/limiter.py).
# .env.example ships the line commented out, so set it for this start only, in the shell;
# the "restore regular dev mode" step below starts the backend again without it.
LOAD_TESTING=true docker compose up -d backend

# The password is read from the environment so it does not appear in ps output
K6_PASSWORD='MySecret123!' make loadtest-seed

# Options (environment variables):
# USER_COUNT=200             users to create (default 100)
# SEED_ARGS='--items-per-org 500 --limit-orgs 10 --clean'
#                            passed to seed_load_test_data.py (default 300 items/org)
```

`users.csv` is git-ignored because it holds the shared password — every clone generates its own with
this step. The two seeders can still be run on their own (`backend/seed_load_test_users.py --stdout`,
`backend/seed_load_test_data.py`).

Expiry date distribution: on the cold-storage and shelf locations (80% of the items) ~15% expired,
~30% expiring in ≤90 days, ~25% OK, ~30% no date; on the freezer (20%) ~10% no date and the rest
1–18 months out. Over everything: ~12% expired, ~26% expiring in ≤90 days, ~36% later, ~26% no date.
Exercises: `GET /api/v1/items`, `?search=`, `/api/v1/items/expiring`, `/api/v1/stats/overview`,
`/api/v1/stats/by-location`, `/api/v1/stats/expiry-forecast`, `/api/v1/stats/rotation-analysis`.

---

### Running a scenario
```bash
# Typical user (read-heavy + dashboard stats)
docker compose -f docker-compose.loadtest.yml run --rm k6 \
  run /scenarios/browse_and_scan.js \
  -e BASE_URL=https://your-domain.com

# Write-heavy
docker compose -f docker-compose.loadtest.yml run --rm k6 \
  run /scenarios/write_operations.js \
  -e BASE_URL=https://your-domain.com

# Spike test (find the breaking point)
docker compose -f docker-compose.loadtest.yml run --rm k6 \
  run /scenarios/spike_test.js \
  -e BASE_URL=https://your-domain.com
```

### Reading results

| Metric | Good | Warning |
|---|---|---|
| `p95 http_req_duration` | < 500ms | > 1000ms |
| `p99 http_req_duration` | < 800ms | > 2000ms |
| `http_req_failed` | < 0.1% | > 1% |
| `scan_response_time p95` | < 600ms | > 1200ms |

### How many concurrent users can the VPS handle?

Run `browse_and_scan.js` — it ramps up to 100 VU by default.
Watch in Grafana for:
- `p95 > 800ms` → approaching the limit
- `error_rate > 1%` → past the limit
- 5xx errors in the Caddy and backend logs → backend overloaded

On a 4-CPU / 8 GB RAM VPS with the current configuration (`--workers 4`) expect roughly
**50–150 concurrent active users** before p95 exceeds 800ms
(depends on database size and OFF queries). This is an estimate, not a measurement: no run of
these scenarios against that configuration is recorded here.

---

### Production-like backend configuration

To test with a production-equivalent setup (gunicorn + 4 workers, DEBUG=false):
```bash
docker compose stop backend
docker compose -f docker-compose.yml -f docker-compose.loadtest-backend.yml up -d --build backend
```
After testing, restore regular dev mode **and turn the rate limiter back on**:
```bash
docker compose up -d backend    # without LOAD_TESTING in the shell; if you put it in .env, take it out — see below
```

`LOAD_TESTING=true` left behind in `.env` keeps the global rate limiter off for
every later run, stripping brute-force protection without a single log line. The
backend now refuses to start on that combination (`LOAD_TESTING=true` while
`DEBUG` and `TESTING` are both off) and prints how to fix it. The load-test stack
above is the one exception: it opts in explicitly with `LOAD_TESTING_ACK_UNSAFE=true`.

---

## Warehouse scale — one organization of up to a million products

The scenarios above measure many small organizations at once. This measures one
large one: a warehouse of hundreds of thousands of products, every screen and
report it uses daily, against a budget. The results are in
[`docs/SCALE_REPORT.md`](../docs/SCALE_REPORT.md).

### The seeder

`backend/seed_scale_data.py` fills the admin's organization — which must hold no
stock yet — in the shape the posting rules produce:

| Size parameter `--products N` | What it derives |
|---|---|
| products | N product cards, each with a GS1 restricted-circulation EAN-13 (prefix 29) and a SKU |
| categories | 40, each declaring three custom fields the records fill in |
| locations | one warehouse → 10 zones → racks → 8 shelves each, `--shelves` of them (2 000 unless given: the building of a small or medium business, whatever the size of its catalogue), plus a receiving zone of 10 dock lanes |
| records | about 3 N, a third of the products batch-tracked, most of those batches dated |
| anchors | one per group of stock that ever held anything, dock lanes included |
| movements | about 10 N over 400 days: each record received (12% through a dock lane and put away), then dispatched in parts |
| documents | completed receipts (about 25 lines), dispatches (about 10) and put-aways, a quarter of the receipts against a purchase order |
| cost layers | one per receipt and per dispatch, the receipt layers drained first in first out |
| partners | 30 + N / 2 000 suppliers, 100 + N / 250 customers |
| open work | 20 + N / 5 000 confirmed purchase orders with their receipts expected, and as many dispatches in draft |

```bash
make db-reset && make db-seed
make create-admin email=admin@example.com password=Admin123 name=Administrator ALLOW_WEAK_PASSWORD=--allow-weak-password
make seed-scale PRODUCTS=100000          # or 500000, 1000000
```

The rows are written by `INSERT ... SELECT` over `generate_series` inside the
database, never through the API: on the 4-core server of the report 100 000 products
seed in 11 minutes and a million in under three hours. Every value is a hash of the
row's number and `--seed`: the same arguments write the same organization. The run
ends with the stock reconciliation over what it wrote (`/stats/reconciliation`), and
any drift between the shelves, the journal and the cost layers fails it. At a million
products that check once needed more than 4 GB of memory, more than the server of the report
had to give it; it compares in the database now and has not been run at that size again.

### The measurement

Seed a stack configured the way production runs — gunicorn with four workers,
`DEBUG` off, and the database tuned as `docker-compose.prod.yml` tunes it
(`docker-compose.scale.yml`):

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.loadtest-backend.yml:docker-compose.scale.yml \
  docker compose up -d db redis backend
(cd frontend && npm run build)           # the phone opens the production bundle
make measure-scale TIER=100k             # → load_tests/scale/results/100k.json
python3 load_tests/scale/measure.py --report load_tests/scale/results/*.json
```

`load_tests/scale/measure.py` (standard library only) times every read behind the
daily screens — `--runs` times each after a warm-up, p50 and p95 of the whole answer
read on the same host — then runs the write paths once each (a 200-line purchase
order received and the receipt undone, five dispatches picked together, a shelf's
stock take, the spreadsheet export, an import of `--import-rows` rows), and has
`frontend/scripts/measure-scale-screens.mjs` open every screen on the phone of the
phone budget (CPU 4x, slow 4G), recording when it is usable and every API request
it sent. Run it with nothing else on the machine: a test suite running beside it
moves the numbers more than the size does.

### On a production server

[`docs/SCALE_REPORT.md`](../docs/SCALE_REPORT.md) was measured on a server deployed
with `docker-compose.prod.yml`, which a development stack only imitates. Three things
differ there.

- **Seed in a container of its own.** `docker exec` into the backend runs the seeder
  inside the backend's memory limit, beside its workers, and one of them pays for it.
  Run it in a one-off container of the backend's image instead, on the stack's network,
  with the backend's environment and a `DATABASE_URL` that reaches the database
  directly as the role that owns the tables (`DB_USER`, not the application's role
  behind PgBouncer): the seeder sets the secondary indexes aside and rebuilds them,
  which only the owner may do:

  ```bash
  img=$(docker inspect -f '{{.Config.Image}}' inventari-backend-1)
  docker run --rm --network inventari_app-network \
    --env-file <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' inventari-backend-1 | grep -v ^DATABASE_URL=) \
    -e DATABASE_URL="postgresql://$DB_USER:$DB_PASSWORD@db:5432/$DB_NAME" \
    --entrypoint python "$img" seed_scale_data.py --products 100000 --email admin@example.com
  ```

  Set the containers' memory limits for the host before seeding, not after: the seed's
  sorts and index rebuilds run inside the database's limit.
- **Keep the rate limiter on.** A server reachable from the internet keeps it, so the
  measurement keeps under it: `--pace 0.35` spaces the requests to under 200 a minute,
  and a 429 that still comes is waited out for as long as its `Retry-After` says.
- **Split the run between two machines.** The server times are only the server's when
  they are taken on its host, and a server has no browser to open the screens with:

  ```bash
  # on the server, from the stack's network straight to the backend
  python3 measure.py --api http://<backend>:8000 --tier 100k --pace 0.35 --skip-browser --out results/100k.json
  # on a workstation, with the server's backend tunnelled to 127.0.0.1:18000
  python3 load_tests/scale/measure.py --api http://127.0.0.1:18000 --tier 100k --pace 0.35 --skip-reads --skip-writes --out load_tests/scale/results/100k.json
  # back on the server: time again, on its host, every request the screens sent
  python3 measure.py --api http://<backend>:8000 --pace 0.35 --retime results/100k.json
  ```

  Each half keeps what the other wrote to the same `--out` file, so the file is copied
  between the machines and both halves end up in one.

---

## Playwright — E2E tests (UI)

### Requirements
- Node.js + running frontend (`npm run dev`) **and** backend (e.g. `make dev-up`).
  Playwright's `webServer` block is **commented out** in `frontend/playwright.config.ts`
  (at the end of the file), so servers are NOT started automatically — you must run them yourself
  before invoking the test runner.

### Install
```bash
cd frontend
npm install
npx playwright install --with-deps chromium
```

### Run

The suite writes to whatever database it runs against, so run it on the
isolated secondary stack, which it provisions itself:

```bash
make test-e2e-isolated
```

A bare `npx playwright test` targets the primary dev frontend and pollutes
its database; reset that stack afterwards if you run it there. For visual
debugging or a single spec, with the isolated stack already up:

```bash
cd frontend
VITE_API_URL=http://127.0.0.1:5273 npx playwright test --ui
VITE_API_URL=http://127.0.0.1:5273 npx playwright test tests/e2e/auth.spec.ts
```

`frontend/TESTING.md` has the rest.

Environment for local runs (defaults from `frontend/playwright.config.ts`):

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_URL` | `http://127.0.0.1:5173` | Frontend dev server URL — used as Playwright `baseURL` (`use.baseURL` in `playwright.config.ts`) |

### k6 vs Playwright

| | k6 | Playwright |
|---|---|---|
| **Purpose** | How much can the server handle | Whether the UI works correctly |
| **Scale** | 10–500 parallel "users" | 1 user, full browser simulation |
| **Tests** | API backend, latency, errors | Clicks, forms, navigation |
| **When to use** | Before scaling, before release | Regression after UI changes |
