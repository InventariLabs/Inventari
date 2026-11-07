# Backend Conventions (backend/AGENTS.md)

Applies to everything under `backend/` — read together with the root [`AGENTS.md`](../AGENTS.md)
(workflow, branches, gates). Code comments cite these rules as `AGENTS.md §3` / `§4` / `§Backend.N`, and
the unnumbered sections by name (`§Sync/Async`, `§Stock Posting Rules`, `§Cross-Module API`).

## 3. Modular Architecture & DB Access (Friction-Driven Development)

### THE GOLDEN PATH (always prefer this)
- **Use `CoreAPI` (`app.core.public_api`)** for all data interactions in `router.py` and `module.py`.
- `router.py` must **never** import `app.models` or `app.database` directly.
- Use `app.core.deps` for FastAPI dependency injection (`get_async_db`, `get_current_user`, etc.).

### THE ESCAPE HATCH (Core tables, read-only analytics that CoreAPI cannot express)
Isolate the queries in a module-private `*_service.py` (never `router.py` / `module.py`) and declare the
bypass at the top of the file:
```python
# architecture: allow_direct_db_access
# reason: <at least 5 words explaining why CoreAPI is insufficient>
```
`db.commit()`, `db.add()`, `db.delete()`, `db.merge()` are **forbidden** there — all Core writes go through
CoreAPI. A missing/too-short reason or any write makes the architecture linter exit 1, which fails the pre-commit
hook and `make lint`.

### Module-local DB writes (auto-approved)
Writing to tables defined in your own module's `models.py` needs no marker — the linter only guards **Core**
tables (`app.models`). Respect module boundaries: do not import cross-module unless absolutely necessary.

### Transaction ownership: the caller commits, you flush
In `app/services`, `app/core` and `app/modules` the caller owns the transaction: the request-scoped session
(`get_async_db`) commits once, on success, before the response is written. Never call `.commit()` or
`.rollback()` there — a mid-stack commit slices the caller's unit of work in two, a rollback erases what the
caller already wrote (journal entries included). Flush and return; raise and let the caller decide.
The architecture linter gates both operations and does not match by variable name — `sess = db;
await sess.commit()` is a commit like any other. Functions that legitimately hold their own session
(background jobs, module routers with no request scope, seeds/CLI entry points, session wrappers, test
helpers) belong on `app/core/transaction_owner_allowlist.txt`, a positive grant that does not ride the
baseline ratchet. Sites still owing their conversion ride `transaction_ownership_baseline.txt` /
`transaction_rollback_baseline.txt`, keyed per site (`path::qualname@N`) — a second commit in a baselined
function is a new, uncovered site, never a free rider on the old key.

## 4. Core Neutrality (Domain-Agnostic Core)

The Core MUST remain neutral — it serves food tracking, IT equipment, warehouses, and future verticals equally. Before adding anything to Core, apply the **3-Vertical Test**:

> *Would this concept be needed by at least 3 different verticals (e.g., food, equipment, library)?*
> If NO → it belongs in a module, not in Core.

### Rules
- **No domain columns in Core models** (`warranty_until`, `assigned_to`, `equipment_status`, …). Use `meta_data` (JSONB) or module tables.
  Permitted exceptions on `Item`, **not a precedent**: `serial_number` and `expiry_date` (a denormalised cache for non-lot items — authoritative expiry lives on `StockLot`). Do not add further domain date columns; `freeze_date`/`production_date` already moved to `meta_data` (`food` / `manufacturing`).
- **Lot/batch tracking: `StockLot` names the batch, the record holds it.** The stock model keeps one record per batch per owner, so the records' quantities are the only stock number and a quant — read from `stock_quants_from_records` — is their sum: `Item.lot_id` and `Item.owner_id` name the batch and owner a record's stock is in (existing records were assigned, and split where they straddled two batches, by archived migration `lotrec02`). The bridge and a record's move change the record's own batch and owner (consuming a held batch is refused there, disposing of it is not); production takes a draw off the records of the batch and owner it came from, a stock take corrects each batch and owner by its own difference, and the document executor opens a record per batch received and takes records off by the batches the draw plan named. Lots flow from document lines into `Item.lot_id`, recall uses `StockLot.status`, and outflows honour lots through the draw planned from the records (`take_from_the_records_async`, cross-lot FIFO/FEFO). A new path that writes stock sets them.
- **`meta_data` namespace convention.** Write under your module's key — `item.meta_data['equipment'] = {...}`. Flat keys are forbidden.
- **Neutral defaults and vocabulary.** No food-specific defaults in Core — e.g. defaulting `behavior_mode` to `'EXPIRY'`, `allowed_system_fields` that assume `expiry_date`, a `'PANTRY'` fallback. The action and reason vocabulary is `USED` / `DISPOSED`; the food-era `CONSUMED` / `DISCARDED` left the database and the enum before the first release (archived migration `legacyvals01`), so new code reads and writes the neutral pair only.
- **Comments and docstrings** use neutral examples (`Cold Storage`, `Shelf A`, `Receiving`), never `Fridge`/`Pantry`/`Kitchen`.

### Module Extensibility Patterns (use these instead of modifying Core)
`navOverrides`, `i18nOverrides`, `columnContributors`, `bulkActions`, `validationRules`,
`dashboard_widgets`, `field_definitions` on Categories, `permissions` in `manifest.json`, `on_uninstall`.
Documented in `docs/FRONTEND_MODULE_GUIDE.md` (frontend hooks) and `docs/MODULE_CAPABILITIES.md`
"Declaring Permissions" (permission keys live in the module's own `<module>:` namespace).

**⚠️ Adding a new extension point:** wire it in the same change, or attach owned follow-up work to it. An unimplemented hook with no owner is debt, not a feature.

**⚠️ A `permissions` key needs an enforcement point in the same change.** `make lint` blocks a key no
`require_permission` / `require_read_write` / `has_permission` call ever names. Prefer mounting
`require_read_write('<m>:read', '<m>:write')` on the module router — it covers every endpoint, including
ones added later. Enforcing a key also means granting it: wire `default_roles` in the same change or the
module locks out every ordinary member. A key that genuinely has to wait goes in
`backend/app/core/manifest_permission_deferrals.txt` with an owner and an expiry date.

### Entry vector: where would a module plug in?

A change that lands in Core (`app/core`, `app/models`, `app/services`, or a Core feature's API) is finished
only when its description answers one question: *where would a module from outside change or extend this?*
Exactly one of three answers is admissible:

1. **Here** — the registry, hook, slot or event is in the same diff, with a test in which a module uses it.
   Point at an existing vector first (the list is in `docs/subsystems/CONTRACTS_STABILITY.md`, "Entry vectors")
   before inventing a new one. Example: a pre-post check lets a module stop a posting with its own rule
   (`warehouse_api.register_pre_post_check`, exercised by `test_a_module_can_stop_a_posting.py`).
2. **Nowhere, on purpose** — the behaviour is an invariant of Core and the change says so in a sentence
   naming it. Example: stock posting (ADR-022) and organization scoping are not open to modules; every
   stock change goes through the one posting path so the stock number stays a single number.
3. **Not yet** — the seam is wanted but not built, and a tracked issue or task names the debt. Example: the
   putaway ranking (`ReceiptLocationPlanner`) once read the operator's putaway rules only; that gap was
   recorded as "not yet" until `warehouse_api.register_putaway_criterion` closed it.

Most changes land on answer 2. The question is not a demand that everything be extensible; it is a demand
that the decision is taken while the feature is written, because a seam added later costs several times
more once other code has assumed the list is fixed. A change whose description does not answer it is not
finished.

## 5. Safety
Use `secrets` for tokens, `slowapi` for public endpoints, and encrypt sensitive settings (`app.services.crypto_service`).

---

## 🐍 Backend Engineering Standards (Python / FastAPI)

### 1. Import Conventions
In module `router.py`, import only: `fastapi`, `AsyncSession`, `app.core.contracts` (DTOs), `app.core.deps`
(`get_async_db`, `get_current_user_context`), `app.core.modules.require_module`, `app.core.public_api.core_api`,
`app.i18n.service`, plus **local** `.schemas` / `.services` — never `app.models` / `app.database` (§3 Golden Path).

### 2. Canonical Endpoint Pattern
Endpoints are async (CoreAPI is async-only), mounted on a module-gated router, and start by resolving the org:
```python
router = APIRouter(dependencies=[Depends(require_module('my_module'))])


@router.post('', response_model=MySchema, status_code=201)
async def create_endpoint(
    data: MyCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db),
):
    org_id = require_org(current_user)  # app.core.deps; 403 without an org
    return await create_my_thing(db, data, org_id, current_user.id)
```
For single-resource lookups, fetch via service and raise `NotFoundException(resource, lang)` when missing (see §3).

### 2b. Partial updates: "named null" clears, "absent key" leaves alone
An `XUpdate` schema types every field optional because a PATCH is partial —
but "optional in the schema" and "nullable in the column" are two different
sets. The contract (same as the PO settings endpoint):

- **Presence is decided where the payload's key set is still visible.**
  The decision reads `data.model_fields_set` (or
  `model_dump(exclude_unset=True)` for dict-shaped services). Most endpoints
  make it at the router, where Pydantic hands the DTO over; a service that
  receives the DTO directly — the PO order update — makes it there instead.
  The place is not the contract: the contract is that the decision happens
  before presence is lost, that an absent key reaches the rest of the code
  as "don't touch" rather than `None`, and that no later layer re-filters
  with a blanket `if value is not None`.
- **A named null is a clearing instruction** for a nullable column: it
  reaches the column as `NULL`.
- **A named null is refused with 400** on a column that cannot take NULL:
  the router names the field — it never forwards the null to `setattr`,
  where the driver turns it into a 500.
- **Value-sentinels only where "clear" means "store a special value"** (an
  empty string, a zero) — not as a substitute for the null the client sent.
- Do **not** re-filter in the service with a blanket `if value is not None`:
  it silently erases the clearing instruction the router already decided.
- **The service-kwargs shape: presence travels as the `UNSET` sentinel.**
  When the update flows into service keyword arguments, the router passes a
  named value straight through and a module-level `UNSET` singleton for every
  **clearable** key the payload omitted: `x=data.x if 'x' in sent else UNSET`.
  A field the refusal already answers (a column that cannot take NULL) needs
  no sentinel — its service parameter stays `T | None = None`, because the
  refusal guarantees `None` never carries an answer there. The clearable
  service parameter is typed `T | None | _Unset` and the branch reads
  `if not isinstance(x, _Unset)` — `None` is a real answer there (the cleared
  nullable column), so `if x is not None` cannot do the branching: it erases
  the difference between "clear it" and "don't touch it".
  `purchase_orders._service_settings` owns the reference implementation, and
  the pricelist and reorder services take the same shape.
- **The refusal speaks one shape, held module-locally.** A §2b refusal is
  the 400 naming every field the payload nulled on a column that cannot take
  NULL. Modules do not import from one another, so the shape is held per
  module, in whichever form fits: `purchase_orders` keeps a
  `refuse_named_nulls(data, {'min_quantity', ...})` helper; `warehouse`
  (putaway rules) and `stock_takes` (cycle counts) raise the same answer inline. What they share — and what the
  tests pin — is the identical message and the refusal set, not the helper.
  Run it at the top of the update endpoint, before the presence-decides
  plumbing.
- **A nullable column can still be refused — as a recorded exception.**
  When the cleared state has no honest answer yet, refuse the named null
  like a column that cannot take NULL, and write the reason both next to
  the call and here. Recorded: `purchase_order.scheduled_date` — the column
  is nullable, but the order number carries the date's period: the number
  is dated by it on create and renumbered when a value change moves the
  date, while the engine's answer for an absent date is "today". Clearing
  the date would strand the number in the old period — or, on the next
  renumber, re-file the order in the current one — behind a PATCH the
  operator read as a date edit. Re-dating by value does that explicitly and
  stays legal; clearing waits for an explicit decision.

Tests pin both halves: a named null reaches the column, and a key left out
leaves it alone (a test that passes in both directions guards only the half
it names — say which in its docstring).

### 3. Error Handling Rules
- **In routers**: answer through the typed `AppException` subclasses in `app/core/exceptions.py` —
  `NotFoundException(resource, lang)` (404), `ForbiddenException(message, lang)` (403),
  `ConflictException(code, message)` (409), `ValidationException(message, field=...)` (400). Each carries
  `detail = {'code': ..., 'message': ...}` (plus `field`/`extra` when given), the envelope the frontend
  branches on with `extractApiErrorCode`. Never let raw Python exceptions leak to the client.
- **In services**: Raise `ValueError` for business rule violations — the router catches and wraps it
  (manually, or via `@map_service_errors` — see §7). A refusal whose sentence is written for a reader
  raises `ServiceRejectionError('<key>')` instead, so the envelope translates it and stamps `lang`.
- **In Pydantic validators**: a `@field_validator` / `@model_validator` refusal flies as a 422, not a 400, and
  the 400 handler never sees it. It raises `ServiceRejectionError('<key>', **kwargs)` too — never
  `ValueError('<sentence>')`. The 422 handler in `app/main.py` finds the exception in pydantic's
  `ctx['error']`, resolves the key in the request language and adds `lang` to that error entry
  (`detail[i].lang`); the frontend keeps reading `detail[i].msg`. Keys live in `app/i18n/_errors_*.py`
  (one file per language, en and pl sharing one; `pt` is a community language), for module schemas too. Inside `app/core/contracts/` import the exception lazily
  inside the validator, as `_system_dtos.py` does. A plain `ValueError('<sentence>')` in a schema lands in
  the `client-422` group of `value_error_sentences_baseline.txt`, and the ledger generator refuses to add it.
- **Do not add raw `raise HTTPException(...)`.** A raw exception answers `detail` as a bare string, so the
  client gets a sentence and no code. `app/core/raw_http_exception_baseline.txt` is empty and the
  architecture lint ratchet holds it there. A new refusal answers through the classes above (or
  `@map_service_errors` in a service); a status the table below has no class for gets one in
  `app/core/exceptions.py`.
- **Standard mapping**:
  | Exception | HTTP Status | When |
  |---|---|---|
  | `ForbiddenException`, or `PermissionError` → it via `@map_service_errors` | 403 | Missing organization / no permission. One shape for this refusal (`{'detail': {'code': 'FORBIDDEN', 'message': ...}}`) whether the decorator or a router raises it — a bare string here used to be the same refusal in a second shape |
  | `QuotaExceededError` → `ForbiddenException` | 403 | The organization stands at a configured limit (`FORBIDDEN` envelope, via `@map_service_errors`) |
  | `TenantIsolationError` → nothing | 500 | The scoped session refused a statement crossing tenants — a defect in the calling code, never a refusal; its message names rows and organizations, so no router or mapping may catch it and hand it to the client |
  | `NotFoundException`, or `EntityNotFoundError` → it via `@map_service_errors` | 404 | Resource not found |
  | `ConflictException(code, message)` | 409 | Duplicate / conflict — e.g. `APPROVAL_REQUIRED`, `RECIPE_IN_USE`; `PeriodClosedError` → `PERIOD_CLOSED` via `@map_service_errors` |
  | `ValidationException`, or `ValueError` → it via `@map_service_errors` | 400 | Invalid business input |
  | `UnprocessableException(code, message, details=...)` | 422 | Well formed, and it cannot be done — e.g. a production order short of stock, with the rows a dialog reads in `details` |
  | `TooManyRequestsException(code, message, details=...)` | 429 | The caller stands at a limit — e.g. `AI_USAGE_LIMIT_EXCEEDED`, with the numbers in `details` |
  | `InterceptorError` → `AppException(422, code, message)` | 422 | Validation in interceptor pipeline |
  | `LlmPurposeUnboundError` → `AppException(503, 'LLM_PURPOSE_UNBOUND', …)` via `@map_service_errors` | 503 | An AI feature whose connection was never chosen — a configuration gap |

  What a `ValueError` answer says is decided by provenance (the rule: the reader
  gets 4xx with a generic message and the details go to the log — a 500 means the programmer did not
  foresee something, which is not what a user should pay for). A sentence this codebase wrote — a plain
  `ValueError` or a subclass defined under `app.*` — reaches the reader as its own text. A library's
  subclass (`pydantic_core.ValidationError`, `json.JSONDecodeError`, ...) is a defect wearing a 400: the
  global handler in `app.main` answers it with the translated `invalid_input` sentence and logs the
  traceback (`is_reader_facing_value_error` in `app/core/exceptions.py` decides; `@map_service_errors`
  leaves the same exceptions to that handler). Everything answered over is logged with its traceback,
  keyed `ServiceRejectionError` rejections excepted — they are expected refusals.

  Code-side, `detail=str(exc)` in a raw `HTTPException` is the same defect as the raw raise: the text of
  an arbitrary exception goes straight to the user. When a service error needs an answer, map it to a
  typed exception with a stable code and a translated (or reader-facing) message.

### 4. Multi-Tenancy Guard
Every query MUST be scoped to `organization_id`. Never return data without filtering by org. `require_org` (`app.core.deps`, see §2) must resolve the tenant at the top of every endpoint that accesses data — as `Depends(require_org)` or `require_org(current_user)`.

### 5. Alembic Migrations
- **Auto-generate first**: `alembic revision --autogenerate -m "short_description"`, then **review the generated file** — auto-generate can miss renamed columns (shows as drop+add); fix manually.
- **Naming**: imperative, lowercase: `"add expiry_date to items"`, `"create webhook_logs table"`.
- **No data migrations in schema files**: backfills get a separate migration file.
- **Indexes and backfills on a table that already holds rows**: build the index `CONCURRENTLY` (autocommit block,
  invalid-leftover guard) and update in committed batches, not one `UPDATE` over the table. The template, and
  which existing revisions fall short of it, is in `docs/subsystems/MIGRATION_OWNERSHIP.md`
  (*Revisions on a Table That Already Holds Rows*).
- **Downgrade**: always implement a working `downgrade()` function.
- **Module tables live in module migrations**: tables defined in `app/modules/<M>/models.py` are created by
  `app/modules/<M>/migrations/versions/`, **never** in core `migrations/versions/baseline_002_full_schema.py` —
  `tests/integration/test_table_ownership.py` fails the suite otherwise. See `docs/subsystems/MIGRATION_OWNERSHIP.md`.
- **Enums are text, never a native PostgreSQL type.** Core stores every enumerated value as text and the
  application owns the vocabulary. A migration creates the column as `varchar` with a
  `CHECK (<column> IN (...))` over the PyEnum members' **values** (lowercase for a `StrEnum`), and the model column
  persists those same values: `Enum(MyEnum, values_callable=lambda x: [e.value for e in x], native_enum=False,
  length=20, create_constraint=True, name='ck_<table>_<column>')`. Never `postgresql.ENUM` / `CREATE TYPE`: a label
  added to a native type later is `ALTER TYPE ... ADD VALUE`, which cannot run in the migration's transaction, in
  every installation, and a renamed one is a type rebuild. A plain `Enum(MyEnum)` would also send member **names**
  (`'DAILY'`), so keep `values_callable`. `tests/integration/test_no_native_enum_types_exist.py` fails on a native
  `Enum` column in the models and on any enum type a migration chain leaves in the database.

### 6. Backend Testing Conventions
- **Location**: Module tests go in `backend/app/modules/<module>/tests/integration/`. Core tests go in `backend/tests/integration/`.
- **Naming**: Classes `Test<Feature>`, methods `test_<verb>_<subject>_<outcome>` (e.g., `test_create_recipe_success`, `test_delete_item_not_found_returns_404`).
- **Marker**: Always use `@pytest.mark.integration` for DB-touching tests.
- **Fixtures**: Use fixtures from `conftest.py` (`db_session`, `client`, `auth_headers`, `test_user`, `test_item`). Do NOT create your own DB sessions.
- **Assertions**: Prefer specific assertions over generic — `assert response.status_code == 201`, `assert result['name'] == 'Test Item'`; NOT `assert response.ok`, `assert result is not None`.
- **Cleanup**: The `db_session` fixture empties the tables between tests (one `DELETE` statement, see `clear_statement` in `backend/tests/_db_hygiene.py`). No manual cleanup needed.

### 7. Canonical Backend Helpers (use these — do not hand-roll)

Each replaces a repeated hand-rolled pattern — do not reinvent them.

- **`paginate_async()` / `paginate()`** (`app.core.db_utils`) — offset pagination returning `(items, total_count)`.
- **`get_org_owned_or_404_async()` / `get_org_owned_or_404()`** (`app.core.db_utils`) — fetch by `(id, organization_id)` or raise `NotFoundException`. Pass `resource=` when the table name does not strip to the i18n `<resource>_not_found` key. This is for **resource lookups**; `require_org` (403) is for tenant presence — not interchangeable. The org is required, and `None` raises rather than querying for rows that belong to nobody — resolve the tenant with `require_org()` first.
- **`@map_service_errors`** (`app.core.exceptions`) — maps service exceptions to the §3 status codes instead of per-endpoint `try/except`.
- **`require_permission(perm)` / `require_read_write(read, write)`** (`app.core.deps`) — dependency factories for gated endpoints. Gate on a permission, never on a role name: a member may hold a custom role whose authority its base level does not describe.
- **`PaginatedResponse.from_slice(...)` / `PaginatedResponse.from_full_list(...)` / `CursorPaginatedResponse.from_cursor_page(...)` / `KeysetPaginatedResponse.from_keyset(...)`** (`app.schemas.pagination`) — the only list envelopes; never invent per-module shapes, and never return a bare `list[...]` from a route (the architecture lint refuses it). A list that grows without bound is paged by the last row seen (keyset), not by `offset`: see `docs/subsystems/PAGINATION.md`.
- **`create_user_async(db, org, ...)`** (`app.core.testing`) — user factory for tests, preferred over hand-built `User(...)`. Its sync/async twin is an accepted polymorphic contract registered in `app/core/sync_async_twin_baseline.txt`.

### 7b. Suppression lists are ratcheted

The architecture gates grandfather known findings in `app/core/*_baseline.txt`, and the entry count
of every one of those lists is recorded in `app/core/baseline_sizes.txt`. A plain lint run fails on
any mismatch in either direction: appending a line to silence a finding, and paying a debt without
lowering the ratchet after it. `python -m app.core.architecture_lint --write-baseline-sizes` is the
only way to change the record, so a suppression always arrives as its own one-line diff.

### 8. File Size & Complexity

No hard LOC limit on files; the guards are function-level — ruff `C901` (complexity ≤ 15) and `PLR0915`
(≤ 50 statements). Split files by responsibility, not by line count.

---

## ⚠️ Backend Anti-Patterns (NEVER do these)

If you generate any of these patterns, correct them immediately:

| ❌ Anti-Pattern | ✅ Correct Pattern |
|---|---|
| Raw `dict` as API response | Define a `Pydantic` schema with `response_model=` |
| `print()` for debugging | Use `logging.getLogger(__name__)` |
| Hardcoded strings in i18n-aware endpoints | Use `get_error_message('key', lang)` — key first, language second |
| Hardcoded English in server-generated content (emails, PDFs, protocols) | Use lang parameter + `_LABELS` dict pattern (see `protocol_service.py`) |

---

## ⚡ Sync/Async Rule

New service functions MUST be async-only. If a sync caller needs access, use an `asyncio.run()` wrapper or
call the async variant directly. Do NOT create parallel sync/async file variants (`foo_sync.py` +
`foo_async.py`) or duplicate sync/async function pairs in the same file — the architecture linter flags them.

**Exceptions**: CLI commands (`app/cli/`) and bulk import (`app/modules/nutrition/import_parquet.py`) may remain sync — this is architecturally correct.

---

## 📦 Data Model (Core)
- **Item**: Unique instance (`STM-XXXX`) or Stock Item (Barcode).
- **StorageLocation**: A tree of any depth, described by `parent_id` alone (ADR-018).
- **Organization**: Top-level tenant container.
- **Item.quantity / StockMove — one model, in every organization** ([ADR-022](../docs/adr/ADR-022-one-number-of-stock.md)).
  **The records** (`Item.quantity`, one record per batch per owner) are the stock — the only number of
  it; `stock_quants_from_records` sums them per (product_template, location, lot, owner) — physical,
  reserved, available — and a "quant" is such a sum (the `stock_quants` table is gone, archived `quantdrop01`).
  **StockMove** is the journal — every change to a record's stock has a movement explaining it,
  posted in the same transaction (see *Stock Posting Rules*).
  - It holds whatever modules are enabled. An organization without a module that reads the register
    (`consumes_stock_quant` — today warehouse, maker, purchase_orders, stock_takes) keeps the same
    movements; only the screens that show them stay behind that list, so a household sees no change.
  - The stock a shelf held before the register knew it was posted once as an opening balance
    (archived `openbal01`, movement `reference_type='opening_balance'`). A record that predates its card adopts
    it on its first change — or on an edit that writes a field to its card — and posts what it held as
    an opening (`opening_balance` movement, layer), then the change as a movement of its own.
  - A record that changes shelves takes its stock with it through one call,
    `_stock_relocation.carry_record_stock_async`, whichever door wrote the shelf.

### 🔄 Stock Posting Rules

Every change to `Item.quantity` posts its movement and its cost layer in the same transaction. A single
record's change goes through `apply_quantity_change_async` (`app.services.items._stock_quant`), which
posts it (`_post_the_change_async`) — the default of every items write (`post_the_change=True`), and of
`core_api.items.create_async` / `update_quantity_async` / `transfer_async`. **A door that moves several records as one
movement writes them with `post_the_change=False` and states them and their movement through one call:
`core_api.stock.post_movement_async`** (receive, issue or transfer; per batch; valuation stays with the
caller) **or, for an outbound draw planned from the records, `core_api.stock.take_from_the_records_async`**
(the records and one movement per shelf and batch taken) — never a record write and
`stock_moves.create_async` as two separate steps, because two calls are two chances to write one. The
receipt, the transfer and the production run's output go through the first; a dispatch, a scrap and the
ingredients a production run draws across shelves go through the second. Stock-take finalize writes
each counted record through its own posting — `reference_type='adjustment'` and the count as the
reference — so the record, the movement and the cost layer move as one write, under
`core_api.stock.lock_async` on the groups it settles. The difference the count found is measured on the
records, which are the state, and the movement ledger is not read to find it — a mismatch the ledger
was already carrying travels with the count, neither cured nor widened, which is what the
reconciliation pairs are there to show. `GET /api/v1/stats/reconciliation` measures the records against
the movement ledger and against the cost layers (**Inventory → Statistics → Reconciliation**); the
scheduled reconciliation warns the organization's admins when a figure changes, and again once a week
while a non-zero one stands unchanged.

**An operation that writes more than one group of stock locks them all first, in one order:
`core_api.stock.lock_async(db, org_id, keys=[(template_id, location_id | None), ...])`** before its
first write. What it locks is each group's anchor (`stock_anchors`); a group is otherwise locked by
whoever writes it, when they get there, and two operations taking the same groups in opposite orders
deadlock — the database aborts one, and a person gets an error for a document or a move nothing was
wrong with. Documents (confirm, complete, cancel, the lines), `post_movement_async`, the record move and
the reservation paths already do; the draws (`take_from_the_records_async`, the reservation finders)
take the same lock before their own ordered read. `None` as the location means every shelf of the
product, the grain a document needs because the cost layers it drains are kept per product. Production
runs are serialized per organization by the maker settings lock, which is why they do not need it.

---

## 🔗 Cross-Module API Contracts

A module exposes other modules exactly one public API (`*_api.py`) — `ApprovalsAPI` is the reference. Rules:

1. **Import only that public API** (and its exceptions) — never another module's models, services, or internal helpers. Import it by its full path (`from app.modules.maker import maker_api`), not package-level (`from app.modules import maker`) — the boundary gate rejects the package form, and the full path is what it suggests on refusal.
2. **Backward-compatible changes only** — additive params, never removing or renaming existing ones.
3. **Graceful degradation** — when the providing module is disabled its methods must no-op or return a sensible default, never crash the consumer.
4. **One entry point per module** — do not create a second public API file.

---

## ✅ Approval Workflow Integration

Integrate via `approvals_api` only (per Cross-Module API Contracts): register a `TargetType`, seed a
workflow in `on_enable`, guard critical operations with `approvals_api.check_and_block(...)`, and expose
thin `request-approval`/`approve` proxy endpoints. **Your module decides WHEN; approvals decides HOW** —
and your module must work when `approvals` is disabled (`check_and_block()` no-ops).

Full step-by-step guide with code examples: `docs/subsystems/APPROVALS.md`.
