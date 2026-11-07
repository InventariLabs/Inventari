# Contracts Stability Policy

**Status:** active
**Enforcement:** DTO, `core_api` signature and module SDK snapshots in `backend/app/core/`, checked by `python manage.py arch lint`; other surface-specific guards are listed below.

This is the compatibility policy for Inventari's public surfaces at **0.11.0**,
including the Core contract layer (`app/core/contracts`). A surface's class,
rather than its presence in the repository or OpenAPI, defines what consumers
can build on.

## 0. Public surfaces in 0.11.0

### The alpha release

0.11.0 is an alpha release so that people can get to know the product. The
weeks after the release are given to paying down technical debt rather than
to new features. That is the intended course of the project.

Three debts were named for those weeks, and all three were paid before 0.11.0
was cut, so the release ships them as part of its contract and no change to
them is planned:

- **Lists.** Every route that returns a collection answers with a pagination
  envelope (`items`, `total`, `limit`, `offset`, `has_more`, or `next_cursor`
  for the cursor feeds), described in [PAGINATION.md](PAGINATION.md). A route
  that deliberately returns a plain array (a fixed vocabulary, the six expiry
  buckets, the newest-N activity feed — 27 routes today) says why beside the
  route with `# list-envelope-exception: <reason>`. The cursor feeds (item
  history, webhook deliveries, the stock movement ledger, the audit journal)
  keep `next_cursor`. The exceptions and the cursor feeds are part of the
  contract, not gaps in it.
- **Refusals.** A business refusal answers with its own code, the upper-cased
  catalogue key, listed in [ERRORS.md](../api/ERRORS.md#refusal-codes).
- **API keys.** A key has its own header, its own permission list and
  permission-bound scopes (the table below).

The rest of the REST API is **experimental** in 0.11: the routes and bodies
that are not lists, errors or keys follow the screens they serve and are still
being shaped (the experimental namespaces in §4 and the frontend module
interface are the clearest examples), and the OpenAPI artifact is checked
against the current code, not against the last release. Consumers should pin
the platform version and read the release notes on upgrade. Module authors can
build on the contract DTOs, stable `core_api` namespaces, manifest and webhook
envelope: these have validation, snapshots or contract tests.

### What the classes promise

**Stable** means compatible evolution from 0.11.0 onward: additions are allowed
when existing consumers continue to work. A breaking change needs a replacement,
a changelog entry and the two-minor-release window in §2. For command and
configuration renames, keep the old command/option or variable as a working
alias during that window. Stability describes the public interface, not frozen
implementation details, output wording or database table layouts.

**Experimental** means a surface may change in a minor release with a changelog
entry and migration instructions, without a deprecation window. Its current
schema describes the current release; it is not a compatibility guarantee.
Consumers should pin the platform version and review release notes on upgrade.

| Public surface | Class in 0.11.0 | Promise and current guard |
|---|---|---|
| Core contract DTOs and enums (`app/core/contracts`) | Stable | Additive-only shapes (§1); `contracts_snapshot.json` and architecture lint (§3, §5). |
| Backend `core_api` facade | Stable, except the experimental namespaces in §4 | Additive-only call signatures; `core_api_snapshot.json` and architecture lint (§5). DTO stability does not automatically extend to REST responses. |
| Backend module SDK (`app.core.module_sdk`) | Stable | The exported names and the hook signatures a module implements are additive-only; `module_sdk_snapshot.json` and architecture lint (§5). It is one of the three paths an installed module may import (`app.core.contracts`, `app.core.public_api`, `app.core.module_sdk`); the other two are covered by their own rows. |
| Module `manifest.json` | Stable | Existing valid manifests remain loadable; the typed `ModuleManifest` schema, loader validation and manifest tests guard the current format. New required fields or renamed vocabulary need the stable window. |
| Outbound webhook envelope | Stable | Version 1 fields and delivery identity remain compatible; `schema_version`, envelope and delivery tests guard the wire format. The event-specific `data` follows its own event contract; see [WEBHOOKS.md](WEBHOOKS.md). |
| Administrator CLI (`python manage.py` documented commands and options) | Stable | Existing documented invocations continue to work; compatible additions are allowed. Human-readable output is not a parsing contract; use a documented structured output where available. |
| Documented environment variable names | Stable | Existing names continue to be accepted. Defaults and operational behaviour can evolve with release notes; secrets and values are not fixed by this promise. |
| Database upgrade path | Stable | Forward migrations preserve existing data from supported released versions. Core and per-module Alembic chains, ownership and round-trip tests guard upgrades; see [MIGRATION_OWNERSHIP.md](MIGRATION_OWNERSHIP.md). This promises an upgrade path, not direct SQL compatibility or a lossless downgrade. Back up before upgrading. |
| REST API, outside the rows below | Experimental | The [OpenAPI artifact](../api/openapi.json) and generated frontend types are checked against the current code, not against the last release. `/api/v1` does not override this alpha classification. |
| REST error shape and refusal codes | Stable from 0.11.0 | An error body is `{"detail": ...}` in one of the three shapes on [ERRORS.md](../api/ERRORS.md); a client reads the object, the list or the string in that order. A documented `code` keeps its meaning and a body may gain fields. A refusal's code is the upper-cased catalogue key. Guarded by the generated refusal-code table, which the test suite checks against the message catalogue, and by the architecture lint's baseline of routes that still answer a bare sentence. |
| REST list and pagination envelopes | Stable from 0.11.0 | A route that returns a collection answers with `PaginatedResponse` (`items`, `total`, `limit`, `offset`, `has_more`), `KeysetPaginatedResponse` (the same plus `next_cursor`) or `CursorPaginatedResponse` (`items`, `next_cursor`, `has_more`), described in [PAGINATION.md](PAGINATION.md). Fields are added, never renamed, removed or repurposed, and a list does not return to a bare array. A dashboard section (`{items, total}`) and the result of an action are documented shapes of their own, not lists. The 27 routes marked `# list-envelope-exception` and the cursor feeds (item history, webhook deliveries, the stock movement ledger, the audit journal) are part of the contract as they stand. Guarded by the architecture lint (`app/core/architecture_lint/_quality_checks_list_envelopes.py`), which refuses a route whose list is `response_model=list[...]`, an optional list or a `-> list[...]` return annotation unless it carries `# list-envelope-exception: <reason>`, and by `make check-openapi-fresh` and `make check-api-types`, which fail when `docs/api/openapi.json` or the generated frontend types drift from the code. |
| API key format, authentication and scopes | Stable from 0.11.0 | A key is `inv_live_` followed by 32 hex characters, sent in the `X-API-Key` header (`API_KEY_HEADER`, `API_KEY_PREFIX` in `app.core.contracts`). It carries its own permission list, chosen when it is issued from what its creator holds; `API_KEY_WITHHELD_PERMISSIONS` can never be on it. A scope is a name a module registers with `register_api_key_scope` and binds to permissions: a scoped key reaches only the endpoints that guard one of them. `Authorization: Bearer <key>` is still accepted through 0.11.x, and every answer to it carries a `Deprecation` header; 0.12 drops it. A new scope, a new permission or a wider default is an addition; renaming or removing a scope, or narrowing what existing keys carry, needs the window in §2 and a migration that keeps issued keys working. Guarded by the api_keys module's tests and its migration test over keys issued before the lists existed. |
| Frontend module interface | Experimental | Module registration, routes, slots, hooks and shared component interfaces may change between minor releases, with release notes. Guarded by the module-contract gate (`frontend/scripts/check-module-contract.mjs`, part of `make check-frontend`), which compares the `FrontendModule` and slot shapes with the snapshot in `frontend/scripts/module-contract.json` and fails on a removed or renamed slot or field, a changed type or a new required field; additions pass. A deliberate break is made by refreshing that snapshot in the same change, so the release notes can name it. |
| Print agent protocol | Stable from 0.11.0 | The registration names the agent's release and the protocol it speaks, and the server refuses a protocol outside `PROTOCOL_MIN_VERSION`–`PROTOCOL_VERSION` (`app.modules.printing.schemas`) with a reason the agent prints; the rule for raising the version is in [PRINTING.md](PRINTING.md). |
| Module package signature format | Stable from 0.11.0 | `module.sig` names its format (`SIGNATURE_FORMAT` in `app/cli/_module_signing.py`, 1 today). A later format is added beside format 1, never in its place, and the verifier keeps reading format 1, so signatures already issued stay valid; a signature in a format this installation does not read is refused at install with the format named. |
| Module settings validator keywords | Experimental | The supported validation vocabulary can change. This is separate from the stable manifest format; current settings schema checks do not promise keyword compatibility across releases. |
| Import/export column headers and file layouts | Experimental | Columns, names and layouts may change with release notes; do not treat a current CSV/XLSX file as a versioned interchange contract. |

A new public surface starts experimental. Promotion to stable requires a
maintainer-reviewed change to this table (or the namespace/method tables below),
a defined contract, a compatibility guard or contract test, and a changelog entry
naming the release from which the promise applies. Stability is not inferred
from usage or age. Moving a stable surface back to experimental is itself a
breaking change: announce it and honour §2 for existing consumers before the
reclassification takes effect. Undocumented implementation details are not
public contracts.

### REST deprecation rule

When deprecating a REST route, its author must:

1. Provide and document the replacement, set `deprecated=True` on the FastAPI
   route so OpenAPI marks it, and return a dated `Deprecation` response header
   from the deprecated route.
2. Add a changelog entry naming the old route, replacement and removal release.
3. For a stable route, keep it working through release N+1 after announcing in
   N; removal is allowed in N+2, two minor releases later (§2). Experimental
   routes may change or be removed in a minor release without that
   window, with the change and migration instructions in the changelog.

This is the author/reviewer rule, not an existing automatic HTTP deprecation
mechanism: 0.11 has no general `Deprecation`/`Sunset` header middleware, and the
published schema currently marks no routes deprecated. Implement the marker
and header when a route is actually deprecated. A change to an experimental route
uses the experimental exception.

### Diagnostic, demo and reference routes in OpenAPI

The schema includes routes for these purposes; their presence does not promote
them to stable integration contracts:

| Routes in `openapi.json` | Purpose and availability |
|---|---|
| `POST /api/v1/ai-connections/test` | Operator diagnostic for stored or draft provider credentials and output capability; it can make a billed provider call. It is an application feature, not a test-suite backdoor. |
| `POST /api/v1/webhooks/endpoints/{webhook_id}/test` | Operator diagnostic that sends a webhook test ping; normal module and authorization guards apply. |
| `POST /api/v1/organizations/my/test-email` | Operator diagnostic that sends a test email; normal authorization applies. |
| `POST /api/v1/demo/sandbox` | Public demo sign-in; answers 404 unless `INVENTARI_DEMO` is enabled. It is not a general provisioning API. |
| `/api/v1/example-widgets` and `/api/v1/example-widgets/{widget_id}` | Reference module CRUD for module authors; available when that module is enabled and the caller has its permissions. Example schemas are experimental, not business integration contracts. |

## 1. The additive-only rule

For every public contract (Pydantic DTO, frozen dataclass DTO, enum):

| Change | Verdict |
|---|---|
| Add a new contract | ✅ allowed |
| Add an **optional** field (has a default) | ✅ allowed |
| Add an enum member | ✅ allowed |
| Relax required → optional (same type) | ✅ allowed |
| Add a **required** field | ❌ breaking |
| Remove or rename a contract / field / enum member | ❌ breaking |
| Change a field's type | ❌ breaking |
| Make an optional field required | ❌ breaking |

Breaking changes are not forbidden forever — they require the **deprecation window** (§2) and an explicit, reviewed snapshot update.

## 2. Deprecation window

1. **Release N:** add the replacement (new field / new contract). Mark the old one deprecated (docstring + `deprecated` note in the changelog). Old and new coexist.
2. **Release N+1:** consumers migrate. Old field still present.
3. **Release N+2 (2 minor releases later):** the old field may be removed — with the removal called out in the changelog.

The lint cannot enforce the window by itself; it enforces that *any* breaking change is deliberate: the snapshot only moves when someone runs the update command and commits the diff, which is visible in PR review.

The window counts from **0.11.0, the first public release**. A surface added
before it and replaced before it had no consumer outside the repository to
protect, so it leaves without a window — the reviewed snapshot diff is the
deliberate step. A removal that lands after 0.11.0 takes the window above.

## 3. The snapshot workflow

- The committed snapshot (`backend/app/core/contracts_snapshot.json`) records every contract: kind (`model` / `enum`), field names, field type reprs, required flags, enum members.
- On every lint run (local pre-commit and CI) the live contracts are diffed against the snapshot. Breaking changes fail the lint with `::error` per change; additive changes pass silently.
- After an intentional contract change, regenerate and commit:

  ```bash
  docker compose exec backend uv run python manage.py arch lint --update-contracts-snapshot
  ```

  The snapshot diff **must be reviewed in the PR** like a migration. A snapshot conflict from parallel PRs resolves by re-running the update command in a separate commit.

- Unit tests: `backend/tests/unit/test_contracts_snapshot.py` (diff rules + drift guard).

## 4. Stability classes

Namespaces of `app/core/public_api` are classified by how strong the stability promise is. **Stable** namespaces follow the additive-only rule strictly from 0.11.0. **Experimental** namespaces may still change shape with a changelog note but without the full deprecation window; they are expected to graduate to stable by 1.0.

### Stable

| Namespace | Covers |
|---|---|
| `items`, `item_history` | item CRUD, lifecycle, history |
| `locations`, `location_types` | storage locations & types |
| `categories` | categories & field definitions |
| `product_templates` | catalog templates, barcode lookup |
| `partners` | suppliers/customers |
| `stock`, `stock_moves`, `valuation` | stock quantities, moves (including the moves of one reference, with their state, and whether stock has left a group since a moment), FIFO/FEFO, valuation |
| `organizations`, `users`, `roles` | tenancy & identity |
| `uoms` | units of measure |
| `attachments`, `file_storage` | files |
| `audit_log` | audit trail reads |
| `labels` | label pools |
| `notifications`, `email`, `announcements` | messaging |
| `settings`, `secrets` | org settings & encrypted secrets |
| `periods` | inventory period guards |
| `queries` | read-side query helpers: analytics read-models, partner display names and ids for the names a screen asks, storage-location display names for a set of ids, the reservations each document holds grouped by product and shelf |

### Experimental

| Namespace | Why experimental |
|---|---|
| `admin`, `ai_usage` | global-admin surface; evolving metrics shape |
| `ai_connections` | LLM provider config; provider matrix still settling |
| `events` | event registration and dispatch interface; exported payload DTOs are covered separately by the contract snapshot |
| `llm`, `pdf`, `scheduler`, `templates` | newer integration namespaces; not yet graduated to stable |

New namespaces start as **experimental** and graduate by maintainer decision recorded here.

### Module APIs: `warehouse_api`

`app.modules.warehouse.warehouse_api.warehouse_api` is the warehouse's door for
other modules — the shipped ones, and a module installed from outside whose
manifest lists `"requires": ["warehouse"]` (the install-time scan opens this one
path to it). Its methods are classified the same way, method by method. A
method is **stable** when it takes and returns only Core contracts
(`app.core.contracts`) and plain values; it is **experimental** when it hands
over the warehouse module's own rows or schemas, whose shape follows the
warehouse screens, or when the feature behind it is still settling. Every
public method is listed here — `test_warehouse_api_stability_list.py` fails
when one is missing.

| Method | Class | What it is for |
|---|---|---|
| `register_pre_post_check` | stable | stop a posting with your own rule — see `CROSS_MODULE_EXTENSION.md` Pattern 6; the check receives `DocumentToPostDTO` and refuses with `InterceptorError`, or answers `'hold'` to park the document for your module; `on_withdrawn` hears of a cancelled or deleted document |
| `get_document_state_async` | experimental | where a document stands — its status, who confirmed it, which module holds it — as `DocumentStateDTO` |
| `document_sign_off_async` | experimental | what the document profile says about signing a document off; read by the approvals module's gate |
| `documents_sign_off_async` | experimental | `document_sign_off_async` for a page of documents in a fixed number of queries; read by the approvals module's list form of the rule |
| `fill_line_tax_rates_async` | experimental | put the rate a document line would take — the product's, its category's, then the profile's default — on your module's own priced lines that name none; the purchase orders' lines are priced this way |
| `hold_document_async` | experimental | park a confirmed document for your module outside a confirmation |
| `release_document_async` | experimental | let a document your module holds go on, posting it when the one-step action submitted it |
| `withdraw_hold_async` | experimental | take a hold back with nothing decided |
| `return_to_draft_async` | experimental | refuse a document your module holds: back to a draft, reservation released |
| `register_work_item_provider` | stable | add tasks to To do and the work board — Pattern 5; the provider answers `WorkItemDTO` tasks |
| `register_pick_order_strategy` | stable | walk the warehouse your own way — Pattern 7; the strategy receives the session's lines as `PickOrderLineDTO` and returns those lines in pick order |
| `register_putaway_criterion` | experimental | turn down shelves a putaway rule would send a receipt line to — Pattern 8; the criterion receives `PutawayCandidateDTO` and answers the shelves that may not take the line |
| `register_document_filter` | stable | narrow the documents list by your module's own fields — the provider answers `DocumentFilterDTO`, the line `meta_data` under your module's name a document must carry |
| `generate_number_async` | stable | the next number in the organization's register for a type |
| `renumber_for_date_async` | stable | keep a number filed in the period its date names |
| `highest_sequence` | stable | seed a register kept outside the documents table |
| `record_count_differences_async` | stable | write the adjustment a count found, from `CountDifferenceDTO` |
| `get_pending_receipt_quantities_async` | stable | per order line, what open receipts still expect |
| `get_active_received_quantities_async` | stable | per order line, what completed receipts brought |
| `in_flight_inbound_map_async` | experimental | per shelf, what confirmed or approval-held transfers have promised into it, in the product's stock unit; a move waiting for a signature is already on its way |
| `list_po_line_ids_with_confirmed_receipt_async` | stable | order lines a confirmed receipt is waiting to receive |
| `search_document_ids_by_number_async` | stable | find documents by their number |
| `putaway_capacity_for_pair_async` | experimental | a shelf's limit for one product; shelf capacity is new in 0.11 |
| `putaway_capacity_map_async` | experimental | the same for many pairs in one read |
| `create_and_confirm_document_async` | experimental | takes the module's `DocumentCreate` and returns its document row |
| `create_document_draft_async` | experimental | the same, left as a draft |
| `set_module_meta_data_async` | experimental | keep your module's own fields on a document or a line, under its name in `meta_data` — see `CROSS_MODULE_EXTENSION.md` Pattern 4 |
| `create_receipt_from_po_async` | experimental | builds a receipt from `ReceiptLineFromPODTO`, returns the document row |
| `list_by_source_po_line_ids_async` | experimental | returns document rows |
| `committed_to_order_lines_async` | experimental | per order line, in the product's stock unit, what documents have already spoken for (a completed receipt what it brought, an open one what it expects), leaving out the document being weighed; for a module's own ceiling on an order |
| `order_surplus_async` | experimental | the over-receipt rule for a quantity past what is left on an order line: the organization's tolerance and hard ceiling and the `warehouse:receive_over_tolerance` permission; answers `None`, or the refusal and the holder's question to raise as `OverReceiptRefusedError` |
| `post_reserve_replenishment_async` | experimental | carries out the reserve move a reorder rule's alert proposes (`ReplenishmentProposalDTO` in, `DocumentStateDTO` out) |
| `get_target_summaries_by_ids_async` | experimental | approval target summaries; the summary shape is not a contract yet |

**`source_po_line_id` is a permanent column.** A document line names the order
line it receives against in `source_po_line_id`, and it stays that way: the
column is the warehouse's record of *which order line this line was received
against*, whatever module wrote the order, and not a dependency on the
purchase orders module — the warehouse never imports it when it loads (its few calls into the orders module reach `purchase_orders_api` only at call time, once that module is installed and enabled; see `backend/app/modules/warehouse/_order_side.py`). A pre-post check sees
it as `DocumentLineToPostDTO.source_po_line_id`, and weighs the line against
its own ordering module (the purchase orders module's over-order check is the
example: `DocumentToPostDTO.may_exceed_over_receipt` carries the posting
person's `warehouse:receive_over_tolerance`). A module that orders by some
other record of its own puts that record's id in the same column; the warehouse
does not read what it points at.

A stable method follows the additive-only rule of §1 for its parameters and
for the contracts it takes and returns (new optional parameters are fine,
removals and renames are breaking); the contracts themselves are in the
snapshot (§3). An experimental method may change with a changelog note.

## 5. Scope & limits

- Covered today: the DTO/enum surface of `app/core/contracts` (DTOs and enums), plus two enums that live outside `contracts.__all__` but that an out-of-repo module names: `SystemEvent` (the event names it subscribes to — dropping one silences the subscription without an exception) and `LlmCapability` (declared per LLM purpose).
- Public enums deliberately **not** snapshotted: `ManifestCapability` (a vocabulary validated against `manifest.json` at load, never imported by a module), `LlmProvider` / `LlmProtocol` (configured by the operator in the admin UI and stored as strings; no module names them), and every module's own event enum (owned and snapshotted by its module).
- **Event names** — the core table plus every name an in-tree module registers with `register_payload` — are frozen in `backend/app/core/event_names_snapshot.json` by `backend/tests/unit/test_event_names_snapshot.py`: a name may be added, never removed or renamed without a reviewed regeneration (`UPDATE_EVENT_NAMES_SNAPSHOT=1`). A module outside the tree owns the snapshot of its own names.
- Covered by other guards, not by this snapshot: import boundaries (AST lint), ORM leaks in `public_api` (model-leak guard), ORM imports inside `contracts/` (abstraction guard).
- The **module SDK** (`app.core.module_sdk`) is snapshotted in `backend/app/core/module_sdk_snapshot.json` by `app/core/architecture_lint/_module_sdk_snapshot.py`: every exported name, a function's parameters, a class's constructor, bases, methods and properties (with their parameters and abstractness). The diff rejects a removed name, a removed or renamed parameter, a new required parameter, a removed hook, a concrete hook becoming abstract, a new abstract hook, and a changed base class; new names, new optional parameters and new concrete methods pass. Regenerate deliberately with `python manage.py arch lint --update-module-sdk-snapshot` and review the diff. There is no deprecation registry: 0.11.0 is the first release an external module can build against, so a removal before it breaks nobody and after it the snapshot diff is the reviewed decision.
- Method **signatures** of `core_api.*` are snapshotted in `backend/app/core/core_api_snapshot.json` by `app/core/architecture_lint/_core_api_snapshot.py`, alongside the DTO snapshot on every architecture lint run. The guard detects removed namespaces/methods, removed/renamed/reordered parameters, optional parameters becoming required, and new required parameters; additive changes pass. It records parameter names, kinds and requiredness, not annotations, defaults' values or runtime semantics. Regenerate deliberately with `python manage.py arch lint --update-core-api-snapshot` and review the diff. Registered method deprecations in `app/core/_core_api_deprecations.py` allow removal; their deadlines and registration are checked by `backend/tests/unit/test_core_api_deprecations.py`. The snapshot is a guard, not a substitute for the window or review (including the experimental exceptions in §4).
- Event payload DTOs exported by `app/core/contracts` are already in `contracts_snapshot.json` (for example `ItemCreatedPayload`); the event registry lives in `app/core/contracts/events/_registry.py`. The experimental class of the `core_api.events` registration/dispatch interface does not weaken those exported DTO contracts.

## 6. Entry vectors: where a module plugs in

A change to Core says where a module from outside would change or extend it (`backend/AGENTS.md` §4,
`frontend/AGENTS.md` §7). An author answering "here" points at one of these before inventing another.
Stability classes are the ones above; a vector is listed with the file that owns it.

| Entry vector | What a module does with it | Owned in |
|---|---|---|
| Module manifest | declares name, version, permissions, capabilities, `requires` and `optional_requires`, module type and category, and whether it has settings (`has_settings_schema`); navigation and slots are declared by the frontend module, not the manifest | `backend/app/core/module_manifest_schema.py`; `docs/MODULE_CAPABILITIES.md` |
| Module lifecycle | runs code at startup, install, upgrade and uninstall, and registers the module's services, contributions, routes, interceptors and scheduled tasks | `backend/app/core/_base_module.py` (`BaseModule`) and `backend/app/core/define_module.py` (`define_module`); [MODULES_GUIDE.md](../../MODULES_GUIDE.md), "Creating a New Module" |
| Events | subscribes to or emits `<module>.<event>`, with payload DTOs from `app.core.contracts`, and registers the payload model of its own events with `core_api.events.register_payload` | `backend/app/core/public_api/events.py`, `backend/app/core/contracts/events/_registry.py`; [EVENTS.md](EVENTS.md) |
| Interceptors | runs before or after an item, storage-location or category write, inside the write's transaction; a `before_*` hook may amend the data or refuse the write with `InterceptorError` | `backend/app/core/_interceptor_base.py` (`ItemInterceptor`, `StorageInterceptor`, `CategoryInterceptor`, `InterceptorError`) and `backend/app/core/_interceptor_pipeline.py`; declared with `define_module(interceptors=[...])` or the `item_interceptors`, `storage_interceptors` and `category_interceptors` contribution points; [ADR-007](../adr/ADR-007-interceptors-and-eventbus.md) |
| Scheduled tasks | runs a periodic task under `<module>.<name>` | `backend/app/core/public_api/scheduler.py` (`core_api.scheduler.register_task`); `schedules=[ModuleScheduledTask(...)]` in `define_module` (`backend/app/core/define_module.py`) |
| LLM purposes | declares an AI purpose a feature uses, with its capability, label and owning module, so the settings screen can bind a connection to it | `backend/app/core/public_api/llm.py` (`core_api.llm.register_purpose`); `LlmCapability` in `backend/app/core/contracts/_system_dtos.py` |
| Contributions | supplies a quota provider, an upload-path resolver or the ownership metadata of files under `/uploads/` | `backend/app/core/contributions.py` (`contribution_registry`, `QuotaProvider`, `UploadPathResolver`, `OwnedFileMeta`, all exported by `app.core.module_sdk`); [MODULES_GUIDE.md](../../MODULES_GUIDE.md), "Contribution Points" |
| Scan providers | answers "what is this code?" at a chosen priority | `backend/app/core/scan_registry.py`; [SCAN.md](SCAN.md) |
| Work-item providers | adds tasks to To do and the work board | `backend/app/modules/warehouse/work_item_providers.py` (`warehouse_api.register_work_item_provider`); [CROSS_MODULE_EXTENSION.md](CROSS_MODULE_EXTENSION.md) Pattern 5 |
| Pre-post checks | stops a posting, or parks the document for the module | `backend/app/modules/warehouse/pre_post_checks.py` (`warehouse_api.register_pre_post_check`); [CROSS_MODULE_EXTENSION.md](CROSS_MODULE_EXTENSION.md) Pattern 6 |
| Document filters | narrows the documents list (History) by the module's own line fields, on the server | `backend/app/modules/warehouse/document_filters.py` (`warehouse_api.register_document_filter`); the frontend half is `documentFilterContributors` in `docs/FRONTEND_MODULE_GUIDE.md` |
| Document metadata | keeps a module's fields on a document or line under its own key | `backend/app/modules/warehouse/warehouse_api.py` (`set_module_meta_data_async`); [CROSS_MODULE_EXTENSION.md](CROSS_MODULE_EXTENSION.md) Pattern 4 |
| Document columns and actions | adds columns to the documents list or buttons to a document's action row | `documentColumnContributors` and `documentActionContributors` in `frontend/src/lib/moduleRegistry/moduleInterfaces.ts` |
| Product list columns and filters | adds columns and filter chips to the Core product list | `frontend/src/lib/moduleRegistry/moduleInterfaces.ts` (`columnContributors`, `listFilterContributors`); [FRONTEND_MODULE_GUIDE.md](../FRONTEND_MODULE_GUIDE.md) |
| Frontend module | registers slots, settings sections, the launcher tile, module navigation, launcher hooks and the command-palette search | `frontend/src/lib/moduleRegistry/moduleInterfaces.ts` (`FrontendModule`); [FRONTEND_MODULE_GUIDE.md](../FRONTEND_MODULE_GUIDE.md) |
| Frontend slots | renders a component inside a Core screen | `frontend/src/lib/moduleRegistry/slotProps.ts`; `docs/FRONTEND_MODULE_GUIDE.md` "UI Slots" |
| Label pools and print templates | reads and issues label codes; supplies the label image renderers and document templates | `backend/app/core/public_api/labels.py`, `backend/app/core/label_rendering.py`, `backend/app/core/public_api/templates.py` |
| API key scopes and permissions | declares a permission in its manifest, guards its endpoints with it (`require_permission`), and registers a key scope bound to it with `register_api_key_scope`; a key can then be issued with that permission, or confined to that scope and reach those endpoints only | `backend/app/core/api_key_auth.py`, exported by `app.core.module_sdk`; the printing module's `printing` scope is the example |
| Export enrichers | adds a module's own columns to the XLSX export of Core rows | `backend/app/core/export_enrichers.py` (`register_export_enricher`); in-tree modules import it from Core directly, and `app.core.module_sdk` does not re-export it, so a module installed from outside has no door to it |
| Record placement | lets a module say where its records stand while they are away from their home location | `backend/app/core/module_ownership.py` (`register_record_placement`); in-tree only, as for export enrichers |
| Template ranking | orders product templates by a module's usage ranking | `backend/app/core/template_ranking.py` (`register_template_ranker`); in-tree only, as for export enrichers |
| Supplier prices | supplies organization-scoped supplier prices to cost estimates | `backend/app/core/cost_estimates.py` (`register_supplier_price_provider`); in-tree only, as for export enrichers |
| Period guard | supplies the closed-period check that Core's stock-changing paths call | `backend/app/core/period_guard.py` (`register_period_guard`); in-tree only, as for export enrichers |
| Product profiles | bundles modules and seed data for a kind of organization | `backend/app/core/product_profiles.py` |
| `core_api` and its queries | reads and writes Core data through the facade; read models in `core_api.queries` | `backend/app/core/public_api/`, `backend/app/core/public_api/queries.py`; [CORE_API.md](CORE_API.md) |
| Putaway criteria | turns down shelves an operator's putaway rule would send a receipt line to (a cold-chain or hazmat check); the ranking walks the rest by capacity, in the plan and the booking alike | `backend/app/modules/warehouse/putaway_criteria.py` (`warehouse_api.register_putaway_criterion`); [CROSS_MODULE_EXTENSION.md](CROSS_MODULE_EXTENSION.md) Pattern 8 |
| Pick order strategies | orders the lines a picker walks through; the organization chooses the strategy in warehouse settings | `backend/app/modules/warehouse/pick_order_strategies.py` (`warehouse_api.register_pick_order_strategy`) |

A new vector is added to this table in the same change that creates it.

### Decisions: shared administration behaviour has no entry vector, on purpose

The answers below were asked of changes to account identity, mail routing, the
language preference and the refusal catalogue. Each is "nowhere, on purpose"
unless it names a seam that already exists; none of them calls for a new hook.

| Behaviour | Decision | Invariant, or the existing seam |
|---|---|---|
| Account identity (sign-in, password reset, who a session belongs to) | Nowhere, on purpose | Only Core's auth services establish who a person is and which organization they belong to. A module receives the result as `UserContextDTO`; it never mints or checks a credential. |
| Mail routing and SMTP authentication | Nowhere, on purpose | One resolver (`_resolve_smtp_config` in `backend/app/services/email_service.py`) picks the server: the organization's own settings, else the installation's. A server the organization names brings its own login or none, so the installation's credentials are never offered to a host an administrator typed; the stored password is encrypted at rest; a demo ignores the organization's server. A module that needs to reach a person addresses the person (`core_api.notifications`), not a mail server. |
| The language preference and the language selector | Nowhere, on purpose | The set of languages is the build's (`frontend/src/i18n/languages.ts`, the list `LanguageSelector` shows), and the preference is the user's. A module adds words in the languages that exist (its own `i18n/<lang>.json`, see below), never a language. |
| The organization's name at onboarding | An existing seam | `core_api.organizations.apply_onboarding_profile_async` takes an optional `organization_name`. The addition is backward compatible: the parameter is optional and appears in `backend/app/core/core_api_snapshot.json` as not required. Covered by the service test (`test_onboarding_profile.py`, a founder's name replaces the default) and the endpoint test (`test_onboarding_setup_access.py`, the name is trimmed); a caller that omits the argument keeps the default name. |
| Translated refusals: `CodedRejectionError` and the catalogue | Nowhere, on purpose, for rendering | Two Core invariants. A refusal is rendered in the request's language by Core's exception handlers (`backend/app/main.py`) from a catalogue key; a module does not render its own. A diagnostic about cryptography — an `UndecryptableSecretError`, a key that no longer opens a secret — is for the operator's log and the `secrets` CLI and never becomes a sentence for a reader: such an error is not reader-facing, and the callers that tell a reader to re-enter a secret say so with a catalogue key of their own. A machine `code` on a `CodedRejectionError` is a client contract, so a module cannot rename or reuse one of Core's. |
| Module-owned refusal messages | An existing seam | The module's `backend/i18n/<lang>.json` (keys at the top level) answers through `get_module_error_message`, which `app.core.module_sdk` exports; English is the catalogue a module must ship and answers for any language or key the module lacks. A module's own refusals use it; nothing new is added for them. |
