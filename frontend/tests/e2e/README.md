# E2E suite — running it and reproducing a clean run

Playwright specs live here. The suite **must** run against the isolated E2E
stack (`make test-e2e-isolated`, via `scripts/dev2`, ports +100) — it pollutes
whatever database it hits.

## The recipe for a clean run on a fresh stack

Every step matters; skipping onboarding is the classic trap:

```bash
# 1. Boot the isolated E2E stack (scripts/dev2, ports +100)
#    --wait: the seed below needs the migrations finished, which a fresh database has not yet
scripts/dev2 docker compose up -d --build --wait --wait-timeout 300

# 2. Seed system data (UOM, storage types) — no organization yet
scripts/dev2 make db-seed

# 3. Create the admin the suite logs in as
scripts/dev2 make create-admin email="admin@example.com" password="Admin123" name="Administrator" ALLOW_WEAK_PASSWORD=--allow-weak-password

# 4. Onboarding — without it every route redirects to the workflow wizard
#    and almost the whole suite fails, including specs that have nothing to
#    do with onboarding. globalSetup does this automatically
#    (idempotent: 409 when already completed); the manual equivalent is:
#    POST /api/v1/onboarding/setup {"profile_id": "food_home"}

# 5. Run the suite (make test-e2e flips the backend to TESTING=true for the
#    password-reset-only _dev_token route and restores it afterwards)
VITE_API_URL=http://127.0.0.1:5273 scripts/dev2 make test-e2e
```

`globalSetup.ts` then handles the rest per run: onboarding-if-needed, enabling
all optional modules, English UI language, leftover-data cleanup, and baseline
seed data (`E2E-Kitchen` storage, `E2E-Dairy` category, three items).

## The dev server runs without hot reload during a run

The stacks serve the frontend with the Vite dev server over the mounted
tree. Vite watches that tree and, when a file it cannot hot-update changes
(any `src/**/i18n/*.json`, `src/main.tsx`), tells every open page to reload.
A checkout, a rebase or the commit hook stashing files while a run is going
is enough, and a spec whose state lives between two actions (tap *More*, then
wait for the link) fails at random: 2 of 20 runs with a translation file
touched every few seconds.

`make test-e2e` (and so `make test-e2e-isolated` and the pool stacks'
wrappers) therefore restarts the dev server with `VITE_DISABLE_HMR=1` for the
length of the run and puts it back afterwards, the way it already does for
the backend's `TESTING` mode. With the flag, `frontend/vite.config.ts` sets
`server.hmr: false`: the pages get no reload channel, while the file watcher
stays on, so the next page load still serves the file as it is on disk. The
same 20 runs pass 60 of 60 under the same storm. A person editing code
outside a run keeps hot reload; one who starts Playwright by hand
(`npx playwright test`) gets the dev server as it is, so
`VITE_DISABLE_HMR=1 docker compose up -d --no-deps frontend` first (and
without the variable afterwards) gives that run the same protection. Not
affected: CI, where nothing changes the tree during a run, and a production
build, which has no Vite client.

## Conventions the specs rely on

- **Route drift is checked against the app, not memory.** When a helper gets
  `Failed to list …: {"detail":"Not Found"}`, verify the path against the
  backend routers (`app.main:api_v1_router`, module `router.py`) before
  editing anything. The stock ledger lives in the core (`/api/v1/stock-quants`,
  `/stock-lots`, `/stock-moves`); the warehouse module's own routes are all
  under `/api/v1/warehouse/` — `/warehouse/register` is the CSV export, and its
  JSON is `/warehouse/register/summary` and `/warehouse/register/rows`.
- **Outbound documents (INT, SCRAP, …) name stock, not products.** Confirm
  refuses lines that carry only a product name or template — the executors
  move stock by record. Use `api.createIntDocumentWithStock(...)` for
  transfers; it seeds a stocked item per line and references it by `item_id`.
- **Dirty forms ask before they are thrown away**. Cancel on a filled
  form opens a discard confirmation ("Discard" / "Keep editing"); a spec that
  fills the form must click through it before expecting the sheet to close.

## Accessibility scan

`a11y-axe.spec.ts` runs axe-core (WCAG 2.0/2.1 A and AA) on login, onboarding,
the dashboard, the item list and form, storages, a document form and settings.
It fails on a serious or critical violation that `a11y-baseline.json` does not
already cover for that screen; the baseline holds, per rule, the kinds of
element it flagged (tag, class, role, type, `data-testid`), so a new rule fails
and so does a new kind of element under a rule the screen already breaks. A
repeated row or tile is one kind, so the result does not depend on how much
data the stack holds. Every scan attaches its full report (all
impacts, with the offending nodes) to the test — open the HTML report to read
it. Writing the baseline is the suite's job, never a hand edit:

```bash
A11Y_WRITE_BASELINE=1 VITE_API_URL=http://127.0.0.1:5273 \
  npx playwright test a11y-axe --project=chromium --workers=1
```

A frozen kind that no longer fires is reported as a `paid` annotation;
running the command above drops it. The jsx-a11y lint rules have their own
baseline (`scripts/a11y-baseline.json`, `npm run check:a11y-baseline`).

## Step counts of the core tasks

Intuitiveness is how the product wins against heavier systems, and nothing in
a unit test notices a change that makes a core task one tap longer. The ten
core tasks — receive a delivery, receive from a purchase order, issue to a
customer, move between locations, count a shelf, undo a mistake, find where a
product lies, record "I made it", add a first product, approve a document —
each have a spec (`core-task-steps-*.spec.ts`) that walks the shortest honest
path on a desktop and a phone viewport and checks the outcome through the API.

`tests/e2e/helpers/step-counts.ts` counts the path in the page, from the events the
browser raises: **clicks** (trusted `click` events), **fields** (distinct
elements typed into or chosen from) and **screens** (distinct routes visited,
the first included). A spec cannot undercount by taking a shortcut, and a new
confirmation sheet is seen even by a spec written before it. The counts are in
`core-task-steps.baseline.json`; the spec fails when one grows and names the
task, the viewport and the metric. A path that gets shorter passes.

A longer path that is intended (the change says why) is accepted by rewriting
the baseline with the one command that writes it, never by hand:

```bash
npm run test:e2e:steps:write-baseline   # rewrites core-task-steps.baseline.json
npm run test:e2e:steps                  # the same check the full run makes
```

`core-task-steps-gate.spec.ts` tests the gate itself: the counter sees each
kind of step in a real page, one extra click, field or screen fails the
comparison, a task without a baseline fails, and the baseline holds all ten
tasks on both viewports.

## CI runs what the local run runs

The E2E job in `.github/workflows/ci.yml` runs every project in
`playwright.config.ts`, Chromium and WebKit, the same set `make test-e2e`
runs. A project added to the config is in both.

## Named skips

A full run skips only these. A skip because the screen did not show what the
test came for hides a regression, so a spec asserts its fixtures instead.

- `warehouse-location-numbering.spec.ts` — CPU throttling is a Chromium tool;
  the spec runs in `chromium` only, so the guard never fires in a full run.

## Fake camera

`tests/e2e/fixtures/camera.ts` replaces `getUserMedia` with the stream of a canvas, so a spec
decides what the camera sees: `camera.showEan13(code)`, `camera.showQr(text)`,
`camera.hide()`. It also reports the scan lookups the app sent
(`camera.scanRequests()`) and whether the stream was released (`camera.streams()`).
Codes are drawn from `tests/e2e/helpers/barcode.ts`, not from images. Use a phone viewport:
the reader's crop is computed for the viewfinder, and on a wide screen it squashes
the image so a QR code no longer decodes.
