# Inventari: Developer Guide to Modules

Build an application on Inventari by giving a module its own data, rules and
screens. The platform supplies the shared inventory model, organizations,
identity, permissions and common application services. Your module uses
CoreAPI for Core data and keeps its own tables and migrations.

A module can implement a workflow of its own or extend a module your
organization already uses. The warehouse demonstrates the first: a complete
receiving, picking, packing and shipping workflow built on Core. The
[Lot certificates example](examples/lot_certificates/README.md) demonstrates
the second: a separate package adds receipt fields and a rule that refuses
posting until its requirements are met.

For a first package, start with [Module Quick Start](MODULE_QUICKSTART.md).
Use this guide to understand the interfaces and ownership rules, and the
[Advanced Module Guide](docs/MODULE_ADVANCED_GUIDE.md) to connect more complex
workflows. Check the
[compatibility policy](docs/subsystems/CONTRACTS_STABILITY.md) before choosing
interfaces your module will depend on.

---

## CoreAPI examples

These examples show common reads and stock operations through CoreAPI.
The reference below describes the available interfaces.

```python
from app.core.public_api import core_api    # the facade: every Core read and write goes through it

item     = await core_api.items.create_async(db, org_id, data, user)          # → ItemDTO
item     = await core_api.items.get_async(db, org_id, item_id)          # → ItemDTO | None
items    = await core_api.items.list_async(db, org_id, ...)             # → list[ItemDTO]
storage  = await core_api.locations.get_async(db, org_id, storage_id)   # → StorageDTO | None
cats     = await core_api.categories.list_async(db, org_id)             # → list[CategoryDTO]
consumed = await core_api.stock.post_movement_async(db, org_id, template_id, qty, to_location_id=loc_id, reference_type="my_module.receipt", reference_id=rec_id)  # → list[QuantConsumptionDTO]
```

Nearly every method is **async** and says so in its name (`*_async`) — `await` it in routers and services. The synchronous ones are named without the suffix; the ones a module most often calls are `secrets.encrypt_for_module` / `decrypt_for_module`, `settings.encrypt_secret`, `uoms.quantize` / `convert_quantity` / `quantity_step` / `round_up`, `events.subscribe`, `scheduler.register_task`, `email.is_configured` and the `pdf` renderers ([CORE_API.md](docs/subsystems/CORE_API.md) lists the full set).

Stock has no direct quant mutation: goods arrive, leave and move through
`post_movement_async`, which states the reference the movement is
(`reference_type` / `reference_id` are required keyword arguments) — and a
draw is `take_from_the_records_async`.

---

## Contract legality (what a module may import)

Two gates answer this, and they are not the same gate. The **install-time
safety scan** decides whether a module loads: it reads the module's source on
install and on every startup. The **architecture lint** is this repository's
own CI gate over the modules that ship inside it. The first section below is
the surface they both read; the two after it are the two gates.

### The declared surface

<!-- module-import-surface:start -->
A module installed from outside this repository may import `app.` names from
these three paths and nowhere else (its own package aside) — they are the
promise, and everything else under `app.` may be renamed, split or deleted
between releases. The list is `MODULE_IMPORT_SURFACE` in
`backend/app/core/module_safety.py`; `backend/tests/unit/test_the_module_docs_match_the_scan.py`
fails when this block and that tuple drift apart:

- `app.core.contracts`
- `app.core.public_api`
- `app.core.module_sdk`
<!-- module-import-surface:end -->

`app.core.module_sdk` is the one door for everything that makes a module a
module: `define_module`, `BaseModule` and `ModuleMetadata` (with
`ModuleScheduledTask`), `ModuleContext`, the interceptor and contribution
classes, the exception classes, the FastAPI dependencies (`get_async_db`,
`get_current_user_context`, `require_org`, `require_read_write`,
`require_permission`, `require_module`), `get_logger`,
`get_module_error_message` and `get_current_lang`, `ModuleModelBase` (the
declarative base for a module's own tables) and `CoreModelBase` (the base the
modules this repository ships declare on),
`SystemEvent` for a subscription, the migration helpers a revision uses
(`create_table_if_absent`, `create_index_if_absent`,
`relation_exists`, `convert_naive_timestamps_to_utc`), the pagination envelopes
and the helper that pages a query into one (`paginate_async`), the scan and
contribution registries (`scan_registry`, `ScanProvider`,
`contribution_registry`, `QuotaProvider`, `UploadPathResolver`), the interceptor
pipeline, `map_service_errors`, `register_api_key_scope`, the file-reference
helpers and the settings journal. The full list is `__all__` in
`backend/app/core/module_sdk.py`. Adding a name
there is additive and safe; removing one is a reviewed change the SDK snapshot
(`module_sdk_snapshot.json`) refuses to let happen by accident.
`app.core.contracts` carries the DTOs and `ModuleModelBase`, and
`app.core.public_api` carries the `core_api` facade the module reads Core data
through.

### The install-time safety scan

<!-- module-safety-forbidden-imports:start -->
These import paths are refused outright, whatever the manifest declares (the
list is `FORBIDDEN_IMPORT_PREFIXES` in `backend/app/core/module_safety.py`;
`backend/tests/unit/test_the_module_docs_match_the_scan.py` fails when this
block and that tuple drift apart):

- `app.models`
- `app.database`
- `app.core.events.event_bus`
- `app.core._event_bus`
- `subprocess`
- `builtins.eval`
- `builtins.exec`
- `socket`
- `urllib.request`
<!-- module-safety-forbidden-imports:end -->

Every other import is matched against the capability map
([docs/MODULE_CAPABILITIES.md](docs/MODULE_CAPABILITIES.md)): `sqlalchemy` and
`sqlmodel` need the `database` capability, `requests`/`httpx`/`urllib` the
`network` one, `os`/`shutil`/`open` the `filesystem` one, `sys`/`subprocess`
the `process` one. A restricted import the manifest does not declare is
refused.

An `app.` import outside the three paths above is refused with a finding that
names the SDK. That is the rule for a module installed from outside; the
modules this repository ships predate the door, and their current reaches are
frozen in `backend/app/core/module_import_surface_baseline.txt`.

One more door is open to a module installed from outside: the public API of a
module this repository ships, `app.modules.<m>.<m>_api` and exactly that path,
when the module's `manifest.json` lists `<m>` under `requires`. It is how a
module extends the warehouse — `from app.modules.warehouse.warehouse_api
import warehouse_api` with `"requires": ["warehouse"]` (put the same list in
`module.yaml`, which the installer reads to refuse a package whose dependency
is missing). The rest of that module's tree stays closed (its `models`, its
`services`, its package imported as `from app.modules.warehouse import …`),
and so does every module this repository does not ship. What each method of
`warehouse_api` promises is listed, method by method, in
[CONTRACTS_STABILITY.md](docs/subsystems/CONTRACTS_STABILITY.md).

### This repository's own lint (in-repo modules only)

The architecture lint runs in CI over the code that ships here: it refuses
`app.models.*`, `app.schemas.*` and `app.services.*` in module code **and** in
the types a CoreAPI method exposes. A public
CoreAPI signature never takes or returns an ORM model or a type from
`app.models`, `app.schemas`, `app.services` or `app.i18n`: its parameters and
return types are contracts DTOs, stdlib or typing types, `AsyncSession`, or
another `app.core` type a module may name (for example `SystemEvent`), so you
never need to duck-type around an internal schema.

It also holds every shipped module to the declared surface: an import outside
`app.core.contracts`, `app.core.public_api` and `app.core.module_sdk` has to be
listed under that module in `module_import_surface_baseline.txt`, together with
an owner, an expiry and the reason it is still there. An import of another
module's public API is on this list too: it is legal to call, but a new
dependency between two shipped modules is a written decision, the way
`requires` is one for a module installed from outside. The list only shrinks —
moving a file to the SDK drops its paths — and the ratchet in
`baseline_sizes.txt` makes adding one a visible act rather than a quiet edit.

A module the repository ships may also be exempt from the scan's `app.*` bans:
the names in `TRUSTED_SHIPPED_MODULES` (the names on the core-trust list that
also have a directory under `app/modules/`) are, and `CORE_EXEMPTIONS` in
`backend/app/core/module_safety.py` lists, per module, the specific names
(third-party or Core) that the named module may import. Neither exemption
extends to a module installed from outside.

`app.schemas` and `app.services` are internal to Core: an installed module that
imports them is refused outright, and nothing promises their shape between
releases. Do not build on them.

- Contract DTOs use plain primitives where an internal enum would leak (`provider: str`, `capabilities: list[str]`); the facade validates values and converts internally.

### User-context convention

- **New write methods** take `user: UserContextDTO` (full actor context for interceptors/audit).
- **Grandfathered convention:** many methods still take the actor as an id (`user_id`, `actor_user_id`, `created_by`) rather than `user: UserContextDTO` — among them the `items` stock ops, `locations.create_async`, `templates`, the `stock` lot-status calls and most partner, product-template and label writes. They are accepted as-is; don't migrate call sites just for this.
- **System-level methods** without an actor (bootstrap/startup) may use `user_id: UUID | None` — justify in the docstring.

### Cross-tenant security gates

- Every route of a module needs a permission dependency — `require_read_write` on the module's top router, or `require_permission` on the route — or a reason to be open (a public token page, the caller's own records), named in the allowlist of `backend/tests/integration/test_every_route_asks_for_a_permission.py`; that test walks every route the application mounts, a community module's included, and fails on a route with neither. A read — a `GET`, a WebSocket — has a guard that only a `:read` permission passes (every alternative of a `require_any_permission` counts, so "read or write" opens it to the write alone), since the grant to change data is not the grant to see it; one that answers to another grant (an administrator's screen, a machine's credential) is named there with why. An exemption names a method and a path, so the same handler mounted at a second path needs its own.
- `core_api.admin.*` and `core_api.ai_usage.get_global_stats_async` require `user: UserContextDTO` with `is_superuser=True` (raise `PermissionError` otherwise).
- Settings secrets (a `format: secret` field) are bound to your module by the settings PUT itself — nothing to do. Writing one outside that path takes `core_api.settings.encrypt_secret(module_name, value)`; the app-wide path (`crypto_service.encrypt_app_secret`) is core-only — the installation's own credentials, SMTP and provider keys. A module that imports `app.services` at all is refused by the import-surface check; the secret-binding check flags the calls `secrets.encrypt`, `secrets.decrypt` and `settings.encrypt_app_secret`.
- Secrets: use `encrypt_for_module` / `decrypt_for_module` — the owner module is authenticated data inside the cipher (AES-256-GCM), so decrypting another module's secret — or edited stored text — raises `PermissionError`. The unscoped `encrypt` / `decrypt` were removed before this repository went public; a call to them fails at runtime and the architecture lint flags it.
- Files: use `save_for_org_async` / `get_for_org_async` / `get_url_for_org_async` / `delete_for_org_async` / `exists_for_org_async` — the `<org>/<module>/` prefix is enforced, and there is no unscoped form.

> **Caveat:** binding is enforced by the cipher, but identity is still *declarative* — the caller names its own `module_name`, so the gate stops modules reading each other's secrets, not a module lying about who it is. Values written by the retired suffix format and by the removed bare `encrypt` predate binding and are read without verification (app-wide by design); `python manage.py backfill rebind-module-secrets --apply` rewrites the ones stored in module settings so they stop being readable under any name, and re-saving a settings form does the same for one value.

---

## 🏗 Module Architecture

A module is a self-contained directory in `backend/app/modules/` (for API/Logic) and `frontend/src/modules/` (for UI).

### Recommended Structure
```text
app/modules/my_module/
├── __init__.py      # Exports the Module class (inherits from BaseModule)
├── module.py        # Metadata, Registration, and Lifecycle Hooks
├── router.py        # API Endpoints
├── models.py        # Database Models (SQLAlchemy)
├── schemas.py       # Pydantic Schemas
├── service.py       # Business Logic
└── i18n/            # Translations
```

### Enumerated columns are text

Core stores every enumerated value as text; a module does the same. Declare the
column with `Enum(MyEnum, values_callable=lambda x: [e.value for e in x],
native_enum=False, length=20, create_constraint=True, name='ck_<table>_<column>')`
and create it in the migration as `varchar` with a matching `CHECK (<column> IN
(...))`. **Never create a PostgreSQL enum type** (`postgresql.ENUM`,
`CREATE TYPE`): adding a label to one later is `ALTER TYPE ... ADD VALUE`, which
cannot run inside the transaction a migration runs in, in every installation,
whereas a text column's next label is an ordinary constraint swap.
`tests/integration/test_no_native_enum_types_exist.py` fails the suite on one.

---

## 🚀 Creating a New Module

### 1. Scaffold

Use the provided CLI tool to scaffold a new module, backend and frontend in one step:
```bash
make new-module
# Enter the name, e.g.: my_feature
```
The backend will automatically discover and register your module routes at `/api/v1/my-feature/*` on next restart.
The command also rewrites the checked-in contracts that list the module (the catalog and key snapshots, `docs/api/openapi.json`, the generated API types) and adds the module's name to `REPO_SHIPPED_MODULES` in `backend/app/core/module_safety.py`, which the copied manifest needs; [MODULE_QUICKSTART.md](MODULE_QUICKSTART.md) names them and the `git add` that goes with them.

### 2. Frontend Registration
`make new-module` has already written `frontend/src/modules/my_feature/module.ts` — a registration with a page, a launcher tile and a nav entry; do not create it again. Edit it as the module grows. The same shape, trimmed:
```typescript
import { lazy } from "react";
import { Star } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

const MyPage = lazy(() => import("./pages/MyPage"));

moduleRegistry.register({
  name: "my_feature",
  routes: [{ path: "/my-feature", component: MyPage }],
  launcher: {
    displayName: "my_feature:navigation.title",
    description: "my_feature:description",
    icon: Star,
    category: "business",
  },
  moduleNav: {
    basePath: "/my-feature",
    items: [{
      path: "",
      icon: Star,
      labelKey: "my_feature:navigation.myFeature",
    }],
  },
});
```
Without `launcher` the module has no tile and is reachable only by its address. Modules are auto-discovered by Vite via `import.meta.glob`. No manual import in `App.tsx` is needed.

### 3. Backend Module Definition: `define_module()` vs `BaseModule`

Every backend module needs a `module.py` that exports a module object. There are **two ways** to create it:

#### Option A: `define_module()` — declarative (preferred for most modules)

A thin wrapper that returns a `BaseModule` instance. Metadata (name, version, etc.) is read automatically from `manifest.json`.

```python
# module.py
from app.core.module_sdk import define_module
from .router import router

module = define_module(router=router)
```

Parameters (all keyword-only):

| Parameter | Type | Purpose |
|---|---|---|
| `router` | `APIRouter \| None` | Static router object |
| `router_factory` | `Callable[[], APIRouter] \| None` | Lazy factory (for circular imports) |
| `interceptors` | `list[Any] \| None` | Item/Storage/Category interceptors |
| `seed` | `Callable[[UUID, ModuleContext], None] \| None` | Replaces `on_enable` — seed org-specific defaults |
| `schedules` | `list[ModuleScheduledTask] \| None` | Periodic background tasks |
| `on_startup_hook` | `Callable[[ModuleContext], None] \| None` | Sync startup callback |
| `on_startup_async_hook` | `Callable[[ModuleContext], Awaitable[None]] \| None` | Async startup callback |
| `on_install_hook` | `Callable[[ModuleContext], None] \| None` | Runs once per installation, on the first backend boot after the module is installed (after its migrations) — not per organization; that is `seed` |
| `on_install_async_hook` | `Callable[[ModuleContext], Awaitable[None]] \| None` | Async variant (takes priority over sync) |
| `on_uninstall_hook` | `Callable[[ModuleContext], None] \| None` | Runs on `module uninstall --drop-data`, after the module's migrations are downgraded |
| `on_upgrade_hook` | `Callable[[str, ModuleContext], None] \| None` | First boot after the installed version changes; receives the old version. For a per-organization rewrite of stored settings, subclass `BaseModule` and override `on_upgrade_async` (see *Migrating every organization's settings* in [MODULE_ADVANCED_GUIDE.md](docs/MODULE_ADVANCED_GUIDE.md)) |
| `register_services_hook` | `Callable[[ServiceContainer], None] \| None` | Register DI services |
| `register_contributions_hook` | `Callable[[], None] \| None` | Register contribution points |
| `settings_schema` | `dict \| None` | JSON Schema of the module's per-organization settings; set `has_settings_schema: true` in `manifest.json` with it. Its `version` is the settings shape version — see *The settings schema version* in [MODULE_ADVANCED_GUIDE.md](docs/MODULE_ADVANCED_GUIDE.md) |
| `default_settings` | `dict \| None` | Values an organization gets until it overrides them |
| `consumes_stock_quant` | `bool` | Declares that the module reads the stock register (documents, maker, purchase orders, stock takes) and moves stock through the movement ledger; an organization with such a module enabled is offered the stock-movement screens |

**Use `define_module()` when:** your module is primarily a router + optional hooks. Covers ~90% of use cases.

#### Option B: `BaseModule` subclass — full control

Subclass `BaseModule` directly when you need complex lifecycle logic that doesn't fit the declarative hooks:

```python
# module.py
from uuid import UUID

from fastapi import APIRouter

from app.core.module_sdk import BaseModule, ModuleContext, ModuleMetadata
from .router import router

class MyModule(BaseModule):
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="my_module",
            version="0.1.0",
            display_name="My Module",
            description="What the module does, in one sentence.",
            icon="Package",
        )

    def register_routes(self) -> APIRouter:
        return router

    def on_startup(self, context: ModuleContext) -> None:
        super().on_startup(context)
        # Subscribe to events, register scheduled tasks, etc.

    async def on_enable(self, organization_id: UUID, context: ModuleContext) -> None:
        # Seed org-specific storage locations, categories, etc.
        ...

module = MyModule()
```

`ModuleMetadata` requires `name`, `display_name`, `description` and `icon`;
`define_module()` reads all of them from `manifest.json` instead.

**Use `BaseModule` when:** you need custom `on_enable`/`on_disable` logic that doesn't map cleanly to a single `seed` callback, or you need fine-grained control over the lifecycle.

> **`define_module()` internally creates a `_DeclarativeModule(BaseModule)` instance**, so both paths produce the same type — the difference is purely in developer ergonomics.

#### `ModuleScheduledTask`

```python
from datetime import timedelta
from app.core.module_sdk import ModuleScheduledTask, define_module

module = define_module(
    router=router,
    schedules=[
        ModuleScheduledTask(
            name='daily_cleanup',       # unique within module
            interval=timedelta(hours=24),
            handler=my_cleanup_func,     # sync or async, no args
            is_persistent=False,         # True = a due run is queued in Redis and survives a restart; without Redis it runs in this process
        )
    ],
)
```

#### `ModuleContext` — what hooks receive

`ModuleContext` is passed to every lifecycle hook. It provides:

| Method | Signature | Purpose |
|---|---|---|
| `subscribe` | `(event_name: SystemEvent \| str, handler) → None` | Subscribe to system or custom events (auto-scoped to tenant) |
| `emit` | `async (event_name, payload: dict) → None` | Emit a custom event (auto-scoped to tenant) |
| `tenant_session` | `@asynccontextmanager (organization_id) → AsyncModuleScopedSession` (`.raw_session` is the unscoped `AsyncSession`) | Session scoped to the organization you name — the one for background work |
| `global_session` | `@asynccontextmanager → AsyncSession` | Unscoped session (global seeders only) |
| `migrate_settings` | `async (module_name, migrate) → int` | Rewrite every organization's stored settings for a new settings shape; call it from `on_upgrade_async` |

> **Routers and services do NOT receive `ModuleContext`.** If an endpoint needs to emit events, use `core_api.events.emit_transactional_async(db, event, payload)` (it rides the request's transaction), or `core_api.notifications` for in-app triggers.

### How far the automatic tenant filter reaches

`AsyncModuleScopedSession.execute()` injects `WHERE organization_id = …` into
your `SELECT`s. It is a safety net, not a substitute for writing scoped
queries — know where it stops:

| Statement shape | Filtered? |
|---|---|
| `select(Item)`, `select(Item.id)`, `select(func.count(Item.id))` | ✅ automatically |
| `select(aliased(Item))` | ✅ automatically |
| `select(func.count()).select_from(Item)` | ✅ via the FROM clause |
| `select(func.count()).select_from(select(Item).subquery())` | ✅ on the subquery's own column |
| subquery/CTE **without** an `organization_id` column | ⛔ raises `TenantIsolationError` |
| explicit `join(...)` | ✅ each **selected** entity is filtered; ❌ a joined table the statement does not select is not — filter that one yourself |

A join is only partly covered: each entity the statement selects gets its
`organization_id` filter, but a joined table that the statement does not select
gets none, because guessing which side to filter would be worse than doing
nothing. Filter that side yourself. A subquery
that exposes no `organization_id` gives the filter nothing to attach to, so
it is refused rather than silently answered with every tenant's rows —
select `organization_id` inside the subquery, or filter there and use
`raw_session`.

---

## ⚙️ CoreAPI & Data Access

To interact with Inventari's core data, you must use the `CoreAPI`. Direct database access to core models is heavily restricted.

```python
from app.core.public_api import core_api
```

The tables below list the methods a module reaches for most. They are not the whole facade: [`docs/subsystems/CORE_API.md`](docs/subsystems/CORE_API.md) has every namespace and every method, and a method missing here is still part of `core_api`.

### `core_api.items` — `CoreItemsAPI`

| Method | Signature | Description |
|---|---|---|
| `get_async` | `async (db, org_id, item_id) → ItemDTO \| None` | Fetch a single non-deleted item scoped to the org |
| `list_async` | `async (db, org_id, *, storage_location_id?, template_id?, storage_usage?, category_id?, context_tag?, limit?, offset?) → list[ItemDTO]` | List items with optional filters |
| `count_async` | `async (db, org_id, *, is_deleted?, category_id?, context_tag?) → int` | Count items with optional category/context filters |
| `search_cursor_paginated_async` | `async (db, org_id, *, storage_ids?, storage_id?, search?, quantity_above?, cursor_ts?, cursor_id?, limit=50) → CursorPaginatedDTO[ItemDTO]` | Item list with keyset pagination on `created_at`, free-text name search and an optional stock floor |
| `search_stock_summary_async` | `async (db, org_id, *, storage_ids?, search?, quantity_above?, limit=50) → list[tuple[ItemDTO, Decimal, bool]]` | Rows for a picker: distinguishable records individually, interchangeable ones summed per (product, shelf). Each triple is (row, quantity offered, is-summed-group) |
| `existing_ids_async` | `async (db, org_id, item_ids: set[UUID]) → set[UUID]` | The subset of `item_ids` that exist for the org — one query for a whole batch |
| `get_for_update_async` | `async (db, org_id, item_id) → ItemDTO \| None` | Fetch one record with a row-level lock (`SELECT ... FOR NO KEY UPDATE`) for concurrent workflows |
| `find_by_barcode_async` | `async (db, org_id, barcode, *, quantity_positive=True, for_update=False) → ItemDTO \| None` | First record with the barcode; eager-loads UoM and storage location |
| `has_active_barcode_async` | `async (db, org_id, barcode) → bool` | Check whether a barcode exists for this org |
| `create_async` | `async (db, org_id, data, user, *, source_document_id?, ...) → ItemDTO` | Create an item through the interceptor pipeline |
| `update_async` | `async (db, org_id, item_id, data, user) → ItemDTO \| None` | Update item fields |
| `soft_delete_async` | `async (db, org_id, item_id, user, reason?, notes?) → bool` | Soft-delete an item |
| `purge_async` | `async (db, org_id, item_id, user, reason?) → bool` | Permanently delete a record, soft-deleted ones included |
| `bind_template_async` | `async (db, org_id, item_id, template_id, *, user_id?, source_document_id?, unit_confirmed_over_template=False) → ItemDTO \| None` | Point a record at its product card (link + history entry); post its opening balance separately |
| `update_quantity_async` | `async (db, org_id, item_id, quantity, *, user_id, ...) → ItemDTO \| None` | Set item quantity through interceptor pipeline |
| `post_opening_balance_async` | `async (db, org_id, item_id, *, template_id, holding, user_id, location_id?) → None` | Post what a record held before it had a card as its opening balance (movement + cost layer) |
| `transfer_async` | `async (db, org_id, item_id, to_storage_location_id, *, user_id, ...) → ItemDTO \| None` | Move item to different storage |
| `update_meta_data_async` | `async (db, org_id, item_id, namespace, data) → ItemDTO \| None` | Merge data into `meta_data[namespace]` (flush-only) |

`ItemDTO` fields: `id`, `organization_id`, `location_id`, `location_name`, `template_id`, `template_name`, `category_id`, `category` (`CategoryDTO | None`), `name`, `brand`, `uom_id`, `uom_symbol`, `uom` (`UomDTO | None`), `shelf_location`, `quantity`, `barcode`, `purchase_price`, `currency`, `added_date`, `expiry_date`, `image_url`, `meta_data` (namespaced dict), `serial_number`, `lot_id` (the batch whose stock the record holds → `StockLot`), `owner_id` (the partner whose goods these are, for consignment), `is_deleted`, `created_at`, `updated_at`. A record is one batch of one owner on one shelf — see [ADR-022](docs/adr/ADR-022-one-number-of-stock.md).

### `core_api.organizations` — `CoreOrganizationsAPI`

| Method | Signature | Description |
|---|---|---|
| `get_name_async` | `async (db, org_id) → str \| None` | Return the organization display name |
| `get_settings_async` | `async (db, org_id) → dict \| None` | Return decrypted organization settings dict |
| `is_module_enabled_async` | `async (db, org_id, module_name) → bool` | Check whether a module is active for this org |

### `core_api.users` — `CoreUsersAPI`

| Method | Signature | Description |
|---|---|---|
| `get_async` | `async (db, org_id, user_id) → UserProfileDTO \| None` | Fetch a user profile by ID — `org_id` limits it to that organization's members; `None` looks across organizations |
| `get_by_ids_async` | `async (db, org_id, user_ids) → list[UserProfileDTO]` | Batch-load user profiles (single IN-query, avoids N+1) |
| `list_org_members_async` | `async (db, org_id, offset?, limit?, search?) → list[UserDTO]` | All active members of an organization (paginated) |
| `count_async` | `async (db, org_id) → int` | Count users in an organization |

`UserProfileDTO` fields: `id`, `email`, `full_name`, `role`, `organization_id`, `preferred_language` (dataclass in `app/core/contracts/_system_dtos.py`, imported from `app.core.contracts`).

### `core_api.locations` — `CoreStoragesAPI`

| Method | Signature | Description |
|---|---|---|
| `get_async` | `async (db, org_id, storage_id) → StorageDTO \| None` | Fetch a single storage location |
| `find_by_context_tag_async` | `async (db, org_id, context_tag) → StorageDTO \| None` | Find first storage with given context_tag |
| `list_async` | `async (db, org_id, *, context_tag?, usage?, limit?, offset?) → list[StorageDTO]` | List storage locations with optional filters |
| `create_async` | `async (db, org_id, *, name, user_id, description?, behavior_mode?, context_tag?, usage?, parent_id?) → StorageDTO` | Create storage location. `name` and `user_id` are required keyword-only args. Runs interceptors and emits events |
| `count_items_in_location_async` | `async (db, org_id, storage_id) → int` | Count non-deleted items in a storage |
| `count_expiring_soon_async` | `async (db, org_id, storage_id, *, days=7) → int` | Count items whose `expiry_date` falls within `days` |

`StorageDTO` fields: `id`, `organization_id`, `name`, `usage`, `short_code`, `sequence`, `behavior_mode`, `context_tag`, `description`, `parent_id`, `warehouse_config`, `settings`, `location_details`, `context_schema`, `field_definitions`, `created_at`, `location_type_id`, `location_type`.

`CategoryDTO` fields: `id`, `organization_id`, `name`, `code`, `context_tag`, `module_name`, `icon`, `sort_order`, `is_active`, `group_label`, `default_removal_strategy`, `emoji`, `color`, `items_count`, `is_module_owned`, `field_definitions`.

### `core_api.categories` — `CoreCategoriesAPI`

| Method | Signature | Description |
|---|---|---|
| `list_async` | `async (db, org_id) → list[CategoryDTO]` | List all categories for an org |
| `get_by_id_async` | `async (db, org_id, category_id) → CategoryDTO \| None` | Fetch a single category |

### `core_api.settings` — `CoreSettingsAPI`

```python
# Module settings are namespaced per module and written as a whole set of keys
await core_api.settings.set_bulk_async(db, organization_id, "my_module", {"api_key": "k1", "timeout": 30})
timeout = await core_api.settings.get_async(db, organization_id, "my_module", "timeout")
# A key the settings schema marks `format: secret` reads back masked;
# the plaintext is for the module's own runtime use only
api_key = await core_api.settings.get_decrypted_async(db, organization_id, "my_module", "api_key")
```

| Method | Signature | Description |
|---|---|---|
| `get_async` | `async (db, org_id, module_name, key?, default?) → Any` | Read a module setting (or the whole dict if `key=None`); secret leaves come back masked |
| `get_decrypted_async` | `async (db, org_id, module_name, key?, default?) → Any` | The same read with secret leaves decrypted |
| `set_bulk_async` | `async (db, org_id, module_name, values: dict)` | Write settings — the keys given replace the stored ones (flush-only, caller commits) |
| `get_schema_version_async` | `async (db, org_id, module_name) → int` | The settings shape version the stored data was written against |
| `migrate_settings_async` | `async (db, module_name, migrate) → int` | Rewrite every organization's settings for a new shape (flush-only); `ModuleContext.migrate_settings` wraps it |
| `encrypt_secret` | `(module_name, value) → str` | Encrypt a value the way settings store secrets (sync) |

There is no single-key setter and no delete for a module's settings: write the
keys you change with `set_bulk_async`. (System settings have their own
`set_system_setting_async`.)

### `core_api.notifications` — `CoreNotificationsAPI`

| Method | Signature | Description |
|---|---|---|
| `create_async` | `async (db, user_id, title, content, notification_type='info', link?, meta_data?) → NotificationDTO \| None` | Create an in-app notification for a user. Flush-only: the caller commits, then passes the DTO to `publish_async` |
| `publish_async` | `async (db, notifications)` | Push committed notifications to the users' live sessions — call it after your `db.commit()` |
| `notify_org_admins_async` | `async (db, org_id, title, content, notification_type='info', link?, meta_data?)` | Notify every member who administers the organization: the built-in admin role, and any custom role that carries `admin:access` or `system:config:write` |

E-mail is its own sub-API: `core_api.email.send_async(to_email, subject, html_content, smtp_config=None, *, organization_id)`.

### Other sub-APIs

| Sub-API | Description |
|---|---|
| `core_api.product_templates` | `CoreProductTemplatesAPI` — read, find and maintain product templates (`create_async`, `update_async`, `delete_async`, `create_stub_async`); returns `ProductTemplateDTO` |
| `core_api.partners` | `CorePartnersAPI` — create, read, update, and deactivate/activate (no hard delete): `get_async()`, `list_async()`, `ids_named_like_async()`, `list_by_email_async()`, `create_async()`, `update_async()`, `deactivate_async()`, `activate_async()` |
| `core_api.uoms` | `CoreUomsAPI` — units of measure (returns `UomDTO`). `get_async`, `get_by_symbol_async`, `list_for_org_async`, `validate_quantity_precision_async`, `list_categories_for_org_async`, `existing_ids_async`, `to_canonical_measure_async`, `to_stock_uom_async`, and the sync `quantize`, `convert_quantity`, `quantity_step`, `round_up` |
| `core_api.file_storage` | `CoreFileStorageAPI` — save/load/delete files via the storage abstraction: `save_for_org_async` / `get_for_org_async` / `get_url_for_org_async` / `delete_for_org_async` / `exists_for_org_async`, every path under the enforced `<org>/<module>/` prefix |
| `core_api.secrets` | `CoreSecretsAPI` — `encrypt_for_module` / `decrypt_for_module` (sync, isolated per module) and the `MASKED` sentinel |
| `core_api.ai_usage` | `CoreAIUsageAPI` — check AI usage limits, estimate costs |
| `core_api.item_history` | `CoreItemHistoryAPI` — `log_async(db, item_id, org_id, user_id, action, changes)` (flush-only) and `list_for_item_async(db, item_id, org_id, *, limit?, actions?)` |
| `core_api.stock` | `CoreStockAPI` — goods arrive, leave and move through `post_movement_async`; a draw is `take_from_the_records_async` (see the stock rule near the top of this section) |
| `core_api.email` | `CoreEmailAPI` — `send_async()`, `send_with_attachment_async()` and the helpers `render_shell()`, `render_button()`, `render_fallback_link()` and `is_configured()` |

> Full method signatures for all sub-APIs: see `docs/subsystems/CORE_API.md`. The facade has more namespaces than this guide shows (among them `ai_connections`, `announcements`, `attachments`, `audit_log`, `events`, `labels`, `llm`, `location_types`, `periods`, `pdf`, `queries`, `roles`, `scheduler`, `stock_moves`, `templates` and `valuation`); that file lists them all.

### Database Access Exception (CQRS-Lite)
- Always use `CoreAPI` for all standard reads and writes.
- You may bypass CoreAPI and use direct DB access **ONLY for heavy, read-only analytics** (e.g., `GROUP BY`, window functions). Keep it in a `*_service.py` file — a convention of this repository; the linter accepts the marker in any module file.
- To bypass the architecture linter, add `# architecture: allow_direct_db_access` and `# reason: <at least 5 words>` to the file (the position does not matter). In these files any write (`db.commit()`, `db.add(`, `db.delete(`, `db.merge(`, `session.commit()`, `session.add(`, `session.delete(`) is refused — unless the file carries a `# module_writes: <tables>` comment, which lifts the check for the whole file; use it only for tables the module owns.

---

## 📡 Deep Integration (Backend)

> **For advanced features** (lifecycle hooks, event bus, interceptors, scheduled tasks), see
> **[docs/MODULE_ADVANCED_GUIDE.md](docs/MODULE_ADVANCED_GUIDE.md)**.

Inventari provides lifecycle hooks (`on_startup`, `on_enable`, `on_install`), an event bus for
pub/sub between modules, data interceptors for mutating data in flight, and a scheduler for
periodic background tasks. All of these are opt-in — a typical CRUD module only needs `router.py`
and `define_module(router=router)`.

### Extending another module

Inventari gives a module no way to subclass the warehouse, override one of its
methods or add a column to its tables
([CROSS_MODULE_EXTENSION.md](docs/subsystems/CROSS_MODULE_EXTENSION.md) rules out
foreign columns and foreign keys on purpose). A subclass depends on every
private detail of the class under it, so each release of the warehouse could
break each customer's warehouse, and two modules that both override posting
could never be installed together. A seam is a promise with a stated shape —
a pre-post check receives a `DocumentToPostDTO` and lets the posting go on or
refuses it; a pick order receives the lines and returns them in order — so the
warehouse can change everything behind it, any number of modules can plug
into the same seam side by side, and switching a module off for one
organization takes its rule away there and nowhere else. The cost is that a
module can do only what a seam offers. A customisation no seam serves yet is a
request for one (the entry vectors in
[CONTRACTS_STABILITY.md](docs/subsystems/CONTRACTS_STABILITY.md)), not a fork.

The seams a module can plug into are listed, with their stability, in
[CONTRACTS_STABILITY.md](docs/subsystems/CONTRACTS_STABILITY.md) ("Entry
vectors"); the warehouse's are a required field on a document or a line
(`meta_data` and the form slots), a pre-post check, a putaway criterion, a pick
order, To do work items, and a column, a filter and an action on the documents. A module from
outside reaches them through `app.modules.warehouse.warehouse_api` once its
manifest lists `"requires": ["warehouse"]` (see "The install-time safety
scan" above).

The worked example uses the field and form slots, pre-post check, pick order,
and document column, filter and action:
[`examples/lot_certificates`](examples/lot_certificates/), a module that asks
for a certificate number on every received lot, books no receipt whose
certificate is not on file, picks zone by zone with the heaviest lines first,
and shows the certificates on the documents list.
[docs/MODULE_ADVANCED_GUIDE.md](docs/MODULE_ADVANCED_GUIDE.md), "Extending the
warehouse", walks it file by file. The test suite installs it the way a
community module is installed and drives those contributions through the
warehouse, so the example keeps working as long as those seams do.

### Contribution Points

Backend contribution points are registered via `contribution_registry.register(point, contribution)` inside `register_contributions()`.

**Stable points** (have consumers):
| Point | Type | Consumer |
|---|---|---|
| `quota_providers` | `QuotaProvider` | `organizations.py` |
| `item_interceptors` | `ItemInterceptor` | `_base_module.py` wires them into the interceptor pipeline |
| `storage_interceptors` | `StorageInterceptor` | `_base_module.py`, the same way |
| `category_interceptors` | `CategoryInterceptor` | `_base_module.py`, the same way |
| `upload_path_resolvers` | `UploadPathResolver` | `/uploads/{path}` serving route — modules own a path family under `/uploads/` and provide ownership metadata (organization, content_type) so the Core route can serve the file safely |

Two more names are accepted as stable points but no backend code reads them, so registering to them reaches nothing: `scan_providers` (register scan providers with `scan_registry.register(provider, priority)` from `app.core.module_sdk`) and `dashboard_widgets` (a dashboard widget is a frontend `slots` registration).

**Experimental points** (no consumer yet — may change before stabilization):
| Point | Type | Status |
|---|---|---|
| `enrichment_providers` | `BaseContribution` | Reserved for future item enrichment |
| `item_actions` | no contribution class yet | Reserved for context-menu actions on single items |
| `settings_panels` | no contribution class yet | Reserved for module config UI declarations |

> Modules registering to experimental points get an info-level log. Prefer typed slots (frontend) and interceptors (backend) instead.

---

## 🎨 Deep Integration (Frontend)

The frontend `ModuleRegistry` allows you to inject UI into the core application seamlessly.

### 1. UI Slots
You can inject React components into predefined areas of the core UI. Each slot has a typed `data` prop: type your component with `SlotDataMap["<slot>"]` and register it wrapped in `slotComponent()`, which keeps that type at your component and lets the registry hold every slot's components in one list.

```typescript
import { moduleRegistry, slotComponent } from "@/module-sdk";
import type { SlotDataMap } from "@/module-sdk";

// ✅ Typed component — TypeScript enforces the correct data shape
const ExtraFields = ({ data }: { data: SlotDataMap["item_edit_extra"] }) => (
  <div>Custom fields for {data.item.name}</div>
);

moduleRegistry.register({
  name: "my_feature",
  routes: [],
  slots: [
    { slot: "item_edit_extra", component: slotComponent(ExtraFields), priority: 10 }
  ]
});
```

`routes` is the one required field besides `name`; the examples below leave
it out to show only the part they are about.

#### Available Slot Reference

The table of slots, what each one receives and where it renders lives in
[`docs/FRONTEND_MODULE_GUIDE.md`](docs/FRONTEND_MODULE_GUIDE.md), under
"Complete Slot Reference". It is checked against `SlotDataMap` by
`make check-frontend`, so it is the one list to read — this guide keeps no
second copy to drift.

> **Type reference:** All slot shapes are typed in `frontend/src/lib/moduleRegistry/slotProps.ts` via the `SlotDataMap` interface. Import `type { SlotDataMap }` from `@/module-sdk` for compile-time safety.

**`settings_module_card`** — Renders a card/section on the App Store page (`/apps`, Settings → Modules), after the module cards. Use this for module-specific admin settings that don't belong to any existing tab (AI, Email, etc.).
```typescript
const FoodDatabaseSettings = ({ data }: { data: SlotDataMap["settings_module_card"] }) => (
  <Card><CardHeader><CardTitle>Food Database</CardTitle></CardHeader>...</Card>
);
moduleRegistry.register({ name: "nutrition", routes: [], slots: [
  { slot: "settings_module_card", component: slotComponent(FoodDatabaseSettings), priority: 10 }
]});
```

**`storage_detail_extra`** — Renders below the items list on a Storage detail page. The slot receives `storageId` and `storageTypeCode` so you can conditionally render content only for specific storage types.
```typescript
const TemperatureChart = ({ data }: { data: SlotDataMap["storage_detail_extra"] }) => {
  if (!["FREEZER", "FRIDGE"].includes(data.storageTypeCode ?? "")) return null;
  return <SensorChart storageId={data.storageId} />;
};
```

### 2. Bulk Actions
Add actions to the floating bar that appears when one or more items are selected in the list. Only users who may write see the bar.
```typescript
import { Printer } from "lucide-react";

moduleRegistry.register({
  name: "my_feature",
  bulkActions: [
    {
      id: "print_labels",
      labelKey: "my_feature:print",
      icon: Printer,
      handler: async (itemIds) => { /* send to printer API */ }
    }
  ]
});
```

### 3. Launcher Config
Controls how your module appears in the App Launcher (the grid of module tiles). Used by 17+ modules.
```typescript
moduleRegistry.register({
  name: "equipment",
  launcher: {
    displayName: "Equipment Management",
    description: "Track and manage physical assets",
    icon: Wrench,
    category: "business",   // "core" | "business" | "analytics" | "integrations" | "system"
    color: "bg-blue-100 text-blue-700",
    order: 20,
  },
});
```
Set `hidden: true` for infrastructure modules that should not appear in the launcher (e.g. `api_keys`, `printing`, `vision`).

### 4. Settings Sections
Add a page under the Settings sidebar. The component renders inside `SettingsShell`.
```typescript
import { Webhook } from "lucide-react";
import WebhooksPage from "./pages/WebhooksPage";

moduleRegistry.register({
  name: "webhooks",
  settingsSections: [
    {
      title: "webhooks:navigation.webhooks",   // an i18n key
      path: "webhooks",                        // under /settings/
      icon: Webhook,
      component: WebhooksPage,
    },
  ],
});
```

### 5. Search Provider
Register a search source for the command palette (Cmd+K).
```typescript
moduleRegistry.register({
  name: "recipes",
  searchProvider: async (query) => {
    const results = await recipesApi.list({ search: query });
    return results.map((r) => ({
      id: r.id,
      title: r.name,
      subtitle: r.description,
      path: `/recipes/${r.id}`,
      module: "recipes",
    }));
  },
});
```

### 6. Theme Override
Override CSS accent color palette per module (white-labeling). Overrides are applied when the module is active and reverted when disabled.
```typescript
moduleRegistry.register({
  name: "equipment",
  theme: {
    cssVariables: {
      "--color-accent-50":  "219 234 254",
      "--color-accent-100": "191 219 254",
      "--color-accent-200": "147 197 253",
      "--color-accent-500": "59 130 246",
      "--color-accent-600": "37 99 235",
      "--color-accent-700": "29 78 216",
      "--color-accent-800": "30 64 175",
      "--color-accent-900": "30 58 138",
    },
  },
});
```

### 7. Column Contributors
Add custom columns to the Items table. Define what column to show and which module provides the data.
```typescript
moduleRegistry.register({
  name: "equipment",
  columnContributors: [
    {
      key: "warranty_until",
      label: "equipment:columns.warrantyUntil",
      requiredModule: "equipment",
      position: "after-name",        // optional: 'before-actions' | 'after-name'
      width: "1fr",                  // optional, defaults to '1fr'
      render: (item) => {
        const equipment = (item.metadata?.equipment ?? {}) as { warranty_until?: string };
        return equipment.warranty_until ?? "—";
      },
    },
  ],
});
```
The `ColumnContributor` interface (exported from `@/module-sdk`) requires `key`, `label`, `requiredModule`, and `render`. The `maker` module is a working reference: its `columnContributors` entry in `frontend/src/modules/maker/module.ts` adds a "BOM" column and uses `useHasValues` to show it only when a row on the page has a formula.

The warehouse documents take the same contributions keyed by document — a column and a filter chip on the documents list, a button on a document's action row (`documentColumnContributors`, `documentFilterContributors`, `documentActionContributors`); a documents filter is answered on the server by a provider the module registers with `warehouse_api.register_document_filter`. See [docs/FRONTEND_MODULE_GUIDE.md](docs/FRONTEND_MODULE_GUIDE.md), "Contributions to the warehouse documents".

### 8. Action Items & Status Badge
Provide per-item action items (launcher feed) and a status badge (launcher tile count).

```typescript
moduleRegistry.register({
  name: "equipment",
  useActionItems: () => useEquipmentActionItems(),
  useStatusBadge: () => useEquipmentStatusBadge(),
});
```
`useActionItems` returns `ActionItem[]` for the "Things to do" panel. `useStatusBadge` returns `{ count: number; label: string; failed?: boolean } | null` for the launcher tile — `null` while loading or with nothing to show, `failed: true` when the read failed.

### 9. Validation Rules
Declare per-field validation for core item creation/edit forms.
```typescript
moduleRegistry.register({
  name: "my_feature",
  validationRules: [
    {
      form: "item_create",
      field: "name",
      // Return an error message, or null when the value is valid.
      validator: (value) =>
        typeof value === "string" && value.trim() ? null : "Name is required",
      priority: 10,
    },
  ],
});
```

`form` is a closed union (`CoreFormName`): `item_create`, `item_edit`, `storage_create`, `storage_edit`. It is not a free string — a typo used to produce a rule that silently matched nothing. Today only the item forms (`item_create`, `item_edit`) run module rules; the type accepts the storage forms, and no storage form runs them yet.

**Rules run on submit**, after the form's own validation, and:

- **Core errors win.** A rule can add a message to a field the form found no fault with; it cannot overwrite one the form produced. A module must not be able to mask "Name is required".
- **A throwing rule is logged and skipped.** Returning a message is how a rule blocks a save; throwing is a bug in the rule, and must not leave the user unable to save anything. The remaining rules still run.
- **The highest-priority rule owns a field** (lowest `priority` number first, default 100). One message per field.
- **`field: "*"`** is a cross-field rule: the validator gets `undefined` as its value and the whole form as its second argument.

Working example: `frontend/src/modules/example_widgets/module.ts` rejects an item name that is only digits — almost always a barcode scanned into the wrong field.

---

### Standalone Hooks for Module Authors

#### `useModuleQuery`
Drop-in replacement for `useQuery` that auto-disables when the module is off.
```typescript
import { useModuleQuery } from "@/module-sdk";

const { data, isLoading } = useModuleQuery("recipes", {
  queryKey: ["recipes", "list"],
  queryFn: () => fetchRecipes(),
});
```
Used by many modules, for example `stats`, `recipes`, `equipment`, `warehouse` and `purchase_orders`.

#### `useModulePageHeader`
Use it in each module page that renders inside `ModuleShell` or `SettingsShell`. The page hands its title, subtitle, actions and back link to the shell, which draws the header; the hook clears them when the page unmounts. A page that does not call it gets only the title and subtitle of its navigation item, with no actions and no back link.
```typescript
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/module-sdk";

function MyPage() {
  const { t } = useTranslation("my_feature");
  const { setHeader } = useModulePageHeader();
  useEffect(() => {
    setHeader({ title: t("title"), backTo: "/my-feature" });
  }, [setHeader, t]);
  return <div className="space-y-6">...</div>;
}
```
Used by many modules, for example `warehouse`, `purchase_orders`, `recipes`, `api_keys` and `equipment`.

---

## 🗄 Database Migrations

### In-repo modules

A module this repository ships declares its models on the core base, which the
module SDK exports as `CoreModelBase`, in
`app/modules/<module>/models.py`:

```python
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class Ticket(CoreModelBase):
    __tablename__ = 'helpdesk_tickets'

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
```

`CoreModelBase` is the same base Core models on — the module's relationships
reach Core's mapped classes and the test schema is one `create_all` — but its
tables are still created by the module's own chain in
`app/modules/<module>/migrations/versions/`, recorded under
`alembic_version_<module>` — never by a core revision. The first table copies
the pattern of `api_keys/migrations/versions/001_initial.py`; every later one
gets a revision beside it. The steps and the tests that guard them are in
[docs/subsystems/MIGRATION_OWNERSHIP.md](docs/subsystems/MIGRATION_OWNERSHIP.md)
→ *How to Add a New Table to a Module*.

**The largest example is `app/modules/warehouse`.** Its models, documents and
stock reads go through the same three paths an installed module uses:
`app.core.contracts` for DTOs and vocabularies, `app.core.public_api` for data
(partner names, held reservations, movement states, the ledger), and
`app.core.module_sdk` for registration, dependencies, logging, the pagination
envelope and `CoreModelBase`. It is not a pure example of the public surface:
`module_import_surface_baseline.txt` (in `backend/app/core/`) lists the 35
imports it still reaches directly — among them the barcode, PDF, label,
import-sheet, money and period-guard helpers, the event, interceptor and scan
modules, and the `approvals`, `purchase_orders` and `printing` module APIs — and a module
installed from outside the repository is refused for any of them. Read it for
how a substantial module is organised; for code to copy, use
[examples/lot_certificates](examples/lot_certificates/README.md), which imports
only the SDK and the warehouse's public API. When a read is missing, it is
added to `core_api` — not reached around with a join.

### Community modules

A community module cannot use the core's `Base`: it carries Core's metadata,
so a table declared on it would be proposed by Core's autogenerate and created
by a core migration — against the ownership rule above. Its tables inherit the
module model base instead, exported by the contract surface:

```python
from sqlalchemy.orm import Mapped, mapped_column

from app.core.contracts import ModuleModelBase


class Warranty(ModuleModelBase):
    __tablename__ = 'warranty_tracker_warranties'

    id: Mapped[int] = mapped_column(primary_key=True)
```

The import of `sqlalchemy` needs `"database"` in the manifest's `capabilities`.

A column that points at a core table — `organization_id`, pointing at
`organizations.id`, is the usual one — declares no `ForeignKey` on the model.
`ModuleModelBase.metadata` holds only the module's tables, so
`ForeignKey('organizations.id')` has no target to resolve and the first flush
raises `NoReferencedTableError`. The module's own migration declares the
constraint (`sa.ForeignKey('organizations.id', ondelete='CASCADE')` inside its
`op.create_table`): the database enforces it, the core's chain still creates no
module table, and the core's metadata still never learns about the module's.

`ModuleModelBase` has a metadata of its own: the table never enters the core's
metadata, so the core's autogenerate never proposes it and no core migration
creates it. The module's own chain under `backend/migrations/` creates it — the
scaffold ships `env.py`, an initial revision and a starting model to rename —
and the platform applies that chain at startup (`python manage.py db
upgrade-modules`), the first time on the startup after the install. Enabling
the module for an organization runs no migration. Every later change to
`models.py` gets a revision beside the first, its `down_revision` naming the
revision before it.

---

## 🌍 Internationalization (i18n)

Inventari ships six languages — `en`, `pl`, `de`, `fr`, `es` and `pt`
(Português, Brasil). Five are maintained: a change brings all of them. `pt` is
a community language: it may lag behind, and a key it lacks is read in English.
A module you publish from outside this repository must ship **English** and may
ship any of the other five; a module built into the repository ships the five
maintained languages.

- A module cannot add a language the core does not know: the loaders skip a
  file such as `it.json`.
- A language the module has no file for, and a key missing from a file it does
  have, show in English, key by key — on both the backend and the frontend.
- The one way to break this is to ship other catalogs and no `en.json`: there is
  nothing to fall back to, and the frontend shows raw keys. `module validate`
  and `module smoke` report that as an error.
- `module new-community` writes the English catalogs only; `-l pl -l de` adds
  others beside them.

### Backend
Put JSON files in `backend/app/modules/<name>/i18n/` (`en.json` first; `pl.json`,
… optional for an outside module). Use them via:
```python
from app.core.module_sdk import get_module_error_message
message = get_module_error_message("my_module", "error_key")  # the request's language
```

### Frontend
Put the files in `frontend/src/modules/<name>/i18n/` (`en.json` first; `pl.json`,
… optional for an outside module). Nothing registers them: the loader finds every module's catalogs by their
path and serves them under the module's name as the namespace, fetching a
language's file when the app starts in it or switches to it.

Usage in components:
```tsx
const { t } = useTranslation("my_module");
return <h1>{t("title")}</h1>;
```

---

## 🛠 Practical Example: A Working Module

For a complete end-to-end reference, read the built-in **`shopping_lists`** module — a full CRUD module (the smallest worked example is `example_widgets`):
- Backend: `backend/app/modules/shopping_lists/`
- Frontend: `frontend/src/modules/shopping_lists/`

It demonstrates: a declarative `define_module(router=router)` (`module.py`), a thin router that hands its work to a service layer (`shopping_list_service.py`), with helpers that reach Core through `core_api` (`_item_crud.py`), Pydantic schemas, an `i18n/` folder, and a `module.ts` that registers routes and navigation on the frontend.

Other good references:
- `stats` — analytics with read-only direct-DB queries (escape hatch with `# architecture: allow_direct_db_access`).
- `webhooks` — event-bus integration (`context.subscribe(...)` for every event type, in `on_modules_ready`, once every module has started).
- `printing` — file generation and external service calls.

### Steps to enable a built-in module:
1. Built-in modules ship in the repository, under `backend/app/modules/<name>/` and `frontend/src/modules/<name>/`; the backend discovers them at startup and the frontend through Vite's `import.meta.glob`.
2. In the app, open **Settings → Modules** (the App Store, `/apps`) and toggle the module on for the organization. No restart is needed — that is only for a module whose files you have just added (`docker compose restart backend`).

---

## 🎨 Core Overrides (White-Labeling per Organization)

Modules can completely change the look and feel of the interface within a single Organization without touching Core code. The mechanism works **per Organization** — the same server can serve "Green Pantry" and "Grey Workshop" simultaneously, because overrides are evaluated based on the `enabledModules` of the active Organization.

### `navOverrides` — Replace / Hide Navigation Items

Allows you to change the icon or label of any Core navigation item (or items from other modules), or hide it entirely.

```typescript
import { BookOpen } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

moduleRegistry.register({
  name: "library",
  routes: [],
  moduleNav: undefined,
  navOverrides: [
    // Replace icon and label for "/inventory/items" with "Books"
    { targetPath: "/inventory/items", icon: BookOpen, labelKey: "library:nav.books" },
    // Hide Shopping Lists — irrelevant in a library context
    { targetPath: "/shopping-lists", hidden: true },
  ],
});
```

**Interface:**
```typescript
interface NavOverride {
  /** Path of the nav item to override, e.g. "/inventory/locations" */
  targetPath: string;
  /** New icon (optional) */
  icon?: LucideIcon;
  /** New i18n key (optional), e.g. "library:nav.books" */
  labelKey?: string;
  /** If true, the item is completely hidden from the menu */
  hidden?: boolean;
}
```

### `i18nOverrides` — Replace Terms at Runtime

A module can inject its own translations over the core's, overriding key terms (e.g. "Products" → "Animals"). A key names the namespace it targets — `"inventory:nav.items"` is the `nav.items` entry of the `inventory` namespace — and a key without a prefix targets `common`. A key nobody reads changes nothing and raises no warning, so take the key from the screen's own catalog. **Original translations are remembered and automatically restored when the module is disabled.**

```typescript
moduleRegistry.register({
  name: "livestock",
  routes: [],
  moduleNav: undefined,
  i18nOverrides: {
    en: {
      "inventory:nav.items": "Animals",
    },
    de: {
      "inventory:nav.items": "Tiere",
    },
    // pl, fr, es are optional for an outside module: a reader in a language
    // you leave out keeps the core's own wording.
  },
});
```

> **Tip:** Only include the keys you actually want to override. The module does not need to provide a full dictionary — `i18next` will replace only the supplied keys.

### Language changes

`ModulesContext` automatically re-applies overrides on every language change (`i18n.on('languageChanged')`), so the module does not need to handle this itself.

### Admin warning

If a module defines `navOverrides`, `i18nOverrides` or `theme`, its card in the App Store (Settings → Modules) shows a warning badge with an alert icon and the text **Changes the interface** next to it, informing the administrator that enabling this module will change the appearance and/or terminology for the Organization.

### Security and co-existence rules

- **Scope (Organization isolation)**: Overrides apply only in the context of the Organization that has the module enabled. Switching Organization in the top-right UI corner immediately recalculates active overrides.
- **Do not hide critical system paths** (`/admin`, `/settings`) via `hidden: true` — users will lose access to management.
- A module MUST NOT use `navOverrides` to hide paths from other business modules without a clear reason (violation of module boundaries).

---

## ✅ Best Practices
1. **Never import from other modules.** Use the Event Bus or Core Services.
2. **Guard routers with `require_module` + `require_org`.** Every router needs the module guard at the router level and the org guard per endpoint:

   ```python
   from uuid import UUID

   from fastapi import APIRouter, Depends
   from sqlalchemy.ext.asyncio import AsyncSession

   from app.core.contracts import UserContextDTO
   from app.core.module_sdk import (
       get_async_db,
       get_current_user_context,
       require_module,
       require_org,
   )

   router = APIRouter(
       tags=['my-module'],
       dependencies=[Depends(require_module('my_module'))],
   )

   @router.get('')
   async def list_items(
       current_user: UserContextDTO = Depends(get_current_user_context),
       org_id: UUID = Depends(require_org),          # ← returns org_id, raises 403 if none
       db: AsyncSession = Depends(get_async_db),
   ):
       ...
   ```

   > `require_module('name')` — dependency factory. Returns `True` if module is enabled for the user's org, raises `HTTPException(403)` otherwise. Import from `app.core.module_sdk`.
   >
   > `require_org` — dependency that injects `current_user.organization_id` and raises `HTTPException(403)` if the user has no org. Import from `app.core.module_sdk`. Prefer this over a custom `_require_org()` helper.

3. **Lazy load everything** on the frontend to keep the initial bundle small.

---

## 📋 `manifest.json` Reference

Every module must have a `manifest.json` in `backend/app/modules/<name>/`. The schema is strict (`extra='forbid'` — unknown fields are rejected).

### Required Fields

| Field | Type | Constraint |
|---|---|---|
| `name` | `str` | Pattern `^[a-z][a-z0-9_]*$`, must match the directory name |
| `version` | `str` | Semver `^\d+\.\d+\.\d+` |
| `module_type` | `'core' \| 'official' \| 'cloud' \| 'community'` | Who stands behind the module, shown on the store card; a module written outside this repository is `community` |

The pattern is only half of the name rule: the name has to be free as well.
The core answers the names below with its own code or its own files, so
`module install` refuses every one of them with the reason it is taken —
`module validate` and `module new-community` already do, in the same words, before
a module is written around the name — and a directory planted by hand meets
the same list at discovery, plus the first path segment of every core `/api/v1`
route, which comes from the running router and so is not in the list below. The list is
`reserved_module_names()` in `backend/app/core/module_safety.py`; a test reads
this block back against it, so a name added there has to appear here and a
name invented here has nowhere to hide.

<!-- module-reserved-names:start -->
- core feature names: `announcements`, `api_keys`, `categories`, `core`, `items`, `locations`, `printing`, `purchase_orders`, `recipes`, `shopping_lists`, `stats`, `stock_takes`, `warehouse`, `webhooks`
- virtual module names: `partners`
- modules this repository ships: `api_keys`, `approvals`, `equipment`, `example_widgets`, `maker`, `nutrition`, `printing`, `purchase_orders`, `recipes`, `shopping_lists`, `stats`, `stock_takes`, `vision`, `warehouse`, `webhooks`
- core translation namespaces (a module's namespace is its own name, so a module here answers the core's own translation calls): `auth`, `categories`, `common`, `items`, `labels`, `locations`, `modules`, `onboarding`, `permissions`, `scan`
- core frontend directories (directories the core keeps in the frontend source, under `frontend/src/` and under `frontend/src/modules/`): `__mocks__`, `announcements`, `components`, `config`, `contexts`, `hooks`, `i18n`, `inventory`, `launcher`, `lib`, `modules`, `onboarding`, `pages`, `partners`, `settings`, `shared`, `spaces`, `store`, `test`, `types`, `utils`
<!-- module-reserved-names:end -->

### Optional Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `inventari_min_version` | `str` | `''` | Oldest platform version the module is known to run on. A module whose floor is above the running platform is rejected at discovery — see [MODULE_VERSIONING.md](docs/MODULE_VERSIONING.md). Empty means no constraint |
| `display_name` | `str \| None` | `name.title()` | Human-readable name shown in UI |
| `description` | `str \| None` | `None` | Short description |
| `icon` | `str \| None` | `None` | One of the icon names listed under [Icons](#icons) (e.g. `"shopping-cart"`) |
| `manifest_version` | `int` | `1` | Which shape of `manifest.json` the file is written in; 1 is the only shape so far |
| `category` | `'core' \| 'business' \| 'analytics' \| 'integrations' \| 'system' \| 'other'` | `'other'` | Where the module sits in the store |
| `optional_requires` | `list[str]` | `[]` | Modules this one integrates with but does not depend on; enabling is allowed without them and the store says so |
| `is_reference` | `bool` | `False` | A worked example: registered and testable, but not offered in the store or switched on by default |
| `has_settings_schema` | `bool` | `False` | Declares that the module has per-organization settings (a `settings_schema`); a test keeps the two in step |
| `homepage` | `str \| None` | `None` | Project page, carried from `module.yaml` at install time |
| `capabilities` | `list[str]` | `[]` | Declared resources: `network`, `filesystem`, `process`, `database`. Not a security boundary (ADR-019) — it is shown to operators on the store card, so say what the module really touches |
| `requires` | `list[str]` | `[]` | Names of modules that must be enabled first |
| `permissions` | `list[str \| object]` | `[]` | Permission keys the module defines, `"<module>:<action>"`, as strings, or as objects with a required `key` and optional `label_key`, `description_key` and `default_roles` (an object takes no other field). The action comes from a fixed vocabulary — see [Permissions](#permissions) |
| `permission_action_exceptions` | `dict[str, str]` | `{}` | A defined key whose action stands outside the vocabulary, mapped to the reason it does |
| `requires_api_key` | `bool` | `False` | Whether an API key is required to use the module |
| `author` | `str \| None` | `None` | Author name |
| `license` | `str \| None` | `None` | SPDX identifier |

### Icons

The catalogue draws a module's `icon` from a closed list of Lucide icons that ships with the
frontend — not from the whole Lucide set — and a module cannot add to that list. Any other name
is drawn as a generic package icon, and `module validate` and `module install` warn about it,
naming the icon. Write the name in kebab-case (`shopping-cart`); `ShoppingCart` is read the same way.

`apple`, `archive`, `baby`, `backpack`, `bar-chart-3`, `beef`, `beer`, `book-open`, `box`, `building`, `building-2`, `cake-slice`, `camera`, `candy`, `carrot`, `check-check`, `chef-hat`, `cherry`, `clipboard-check`, `coffee`, `container`, `cookie`, `cooking-pot`, `cpu`, `croissant`, `cross`, `cup-soda`, `dog`, `drumstick`, `egg`, `factory`, `file-check`, `fish`, `flask-conical`, `glass-water`, `grape`, `hammer`, `home`, `ice-cream`, `key`, `landmark`, `laptop`, `leaf`, `leafy-green`, `lock`, `milk`, `monitor`, `monitor-smartphone`, `mouse`, `move`, `package`, `pill`, `pizza`, `printer`, `refrigerator`, `sandwich`, `server`, `settings`, `shapes`, `shell`, `shopping-bag`, `shopping-basket`, `shopping-cart`, `smartphone`, `snowflake`, `soap-dispenser-droplet`, `soup`, `stethoscope`, `store`, `thermometer`, `truck`, `utensils`, `warehouse`, `webhook`, `wheat`, `wifi`, `wine`, `wrench`, `zap`

`cheese` and `pint` are accepted as well and drawn as `cookie` and `beer`. Leave `icon` out to get the
package icon on purpose.

### Permissions

A permission key is stored by name in every organization's roles. A key renamed after a release
is a data migration in every installation, so the word is picked once, from one vocabulary:

| Action | Grants |
|---|---|
| `read` | Seeing the module's records |
| `write` | Creating and changing them in day-to-day work |
| `manage` | Setting up and removing what day-to-day work runs on |
| `approve` | Signing off what someone else submitted or a rule held back |
| `configure` | Changing how the module behaves for the organization |
| `consume` | Using stock up through the module — a recipe cooked |
| `extract` | Reading data out of an outside source — a photograph |

Reuse a word before inventing one: a module whose second reader does the same thing as its first
guards both with the same key. `module validate` and `module install` warn about any other action,
naming the key. If a module really needs one, it says why in the manifest, and the warning goes
quiet; the reason is what a reviewer reads:

```json
"permission_action_exceptions": {
  "warehouse:receive_over_tolerance": "An override of one rule, not an action on the records…"
}
```

An entry with an empty reason does not count, and an entry naming a key the module does not
define, or one whose action the vocabulary already covers, draws a warning of its own. Core keys listed as a dependency
(`items:read`, `org:settings:write`) are core's words and are not checked.

**A module that declares no permissions.** Every endpoint is still guarded — a module declares
keys of its own when a role should be able to be refused something the module does and no core
key already says it. A module may declare none when one of these holds:

- **It has no endpoints of its own.** What it contributes is reached through other modules' and
  core's endpoints, under their keys. `nutrition` is this: its product lookup answers a barcode
  scan through the scan registry, and its nutrition table is read off a photograph behind
  `vision:extract`.
- **Every endpoint sits behind a core key or the administrator check, set on the router** so an
  endpoint added later arrives closed. `api_keys` is behind `org:settings:write`; `webhooks` is
  behind the administrator check (the built-in admin level or a role holding `admin:access`).
- **It turns what a member may already read into output, and nothing more.** `printing` renders
  labels of items and locations the member can see and queues them for a printer; its router is
  behind the module switch and organization membership. It does declare one key of its own,
  `printing:agent`, which guards its `/agent/` endpoints — and that key is the whole reach of a
  key issued with the `printing` scope.

A module whose endpoints change records of its own, or hand out something a member could not
read before, declares keys and guards with them — `require_permission('<module>:<action>')`, or
`require_read_write('<module>:read', '<module>:write')` on a router whose reads and writes split
by HTTP method, as `equipment` does.

### Examples

**Minimal:**
```json
{
  "name": "my_module",
  "version": "0.1.0",
  "module_type": "community"
}
```

**Full (official module with dependencies):**
```json
{
  "name": "shopping_lists",
  "version": "0.5.0",
  "inventari_min_version": "0.9.0",
  "display_name": "Shopping Lists",
  "description": "Create and manage shopping lists with automatic suggestions.",
  "icon": "shopping-cart",
  "module_type": "official",
  "category": "business",
  "requires": ["items", "categories"],
  "capabilities": ["database"]
}
```

> **Which number to write:** `version` describes the module, `inventari_min_version`
> describes what it needs underneath. No module in this repository reaches `1.0.0`
> while the platform is on `0.x`. Both rules, and how the floor is enforced, are in
> [MODULE_VERSIONING.md](docs/MODULE_VERSIONING.md).

> **`module_type` trust levels:** the field is what the store shows for a module this repository ships; every other module is shown as `community` whatever its manifest says, and a module from outside the repository that claims `core`, `official` or `cloud` is refused at discovery. So the field can keep a module from loading but cannot raise its trust, and it does **not** change the import rules. How far the AST safety scan relaxes for a given module is decided by name-keyed tables in `backend/app/core/module_safety.py`: `TRUSTED_SHIPPED_MODULES` (the trusted names that have a directory in this repository) lifts the `app.`-internal import bans, `REPO_SHIPPED_MODULES` exempts the modules this repository ships from the module import-surface rule, and `CORE_EXEMPTIONS` grants named modules specific imports, some of them third-party (`printing` runs `subprocess`, `webhooks` speaks `socket`), which the trusted list alone never allows. Two more things shape the scan: the capabilities a module declares, and a `requires` entry that names a module this repository ships. Files under a `tests/` directory are not scanned. A module can sit on one table, on several, or on none: `vision`, `nutrition`, `equipment`, `approvals` and `maker` carry named exemptions without being on the trusted list, and every module outside the tables meets the full vocabulary whatever its `module_type`. Populating `module_type` honestly is the author's job today — the field is not yet verified against a signature (ADR-019).

> **`module_type` and the three trust levels (ADR-019) name different things, and nothing maps one onto the other.** ADR-019 names *who certified* a module — Core (shipped in this repository), Certified (reviewed and signed for the catalog), Foreign (installed from anywhere else) — and that certification is a signature plus identity fields in the tracking file, not a manifest value. The four `module_type` spellings are a label its author writes and the store card prints; the readers in the codebase that decide something from it are the i18n validator (`app/cli/module_validator.py`), where `core` and `official` owe all five languages and the other two owe `en`; the discovery refusal of a module from outside the repository that claims `core`, `official` or `cloud` (`app/core/_registry_class.py`); and the store and `module list` displays (`app/api/modules.py`, `app/cli/commands_module.py`). No level is spelled by this field, and a module's trust does not rise when its author retypes it.

---

## 🔒 Modules & Trust

Module trust is certification and the operator's own responsibility, not
confinement — module code runs in-process with the same database and
filesystem access as the Core. Three levels are named ([ADR-019](docs/adr/ADR-019-modules-are-certified-not-sandboxed.md)):

### 1. Core, Certified, Foreign
- **Core modules** live in `backend/app/modules/`, are reviewed like the rest of the codebase and released with it.
- **Certified modules** are external modules reviewed and signed for the catalog. Signing and verification are built (`module sign`, the installer's signature check, `MODULE_SIGNING_PUBLIC_KEYS`); certification review, an Inventari signing key and a catalogue do not exist yet, so an external module is foreign — trusted only through its author's key listed in `MODULE_SIGNING_PUBLIC_KEYS`.
- **Foreign modules** are installed from any other source, on the operator's own responsibility. Pin the revision (`--rev`, required for git sources), read the diff when you bump it, and install only sources you would trust with your database.

### 2. Capabilities Manifest
If your module uses the network or filesystem, declare it in `manifest.json`. The AST safety scan matches your import statements against the declared vocabulary and refuses the module at load time when an import sits outside it — a review aid and architecture gate, not resource guarding. Relaxations come from three places: the capabilities you declare (an import the scan would report as undeclared is allowed when its capability is listed); the name-keyed tables in `app/core/module_safety.py` (`TRUSTED_SHIPPED_MODULES`, `REPO_SHIPPED_MODULES`, `CORE_EXEMPTIONS`), which a package cannot join and which are described under Module Capabilities below; and a `requires` entry that names a module this repository ships, which opens that module's `<name>_api` package to yours.
```json
{
  "name": "weather_widget",
  "version": "0.1.0",
  "module_type": "community",
  "inventari_min_version": "0.9.0",
  "capabilities": ["network"]
}
```

### 3. Validation Tool
Always run the validation script before submitting a module:
```bash
python manage.py module validate --module my_module
```
Use `--allow-core` only if you are working on official core modules.

---

## 📦 Community Module Distribution

Community modules are self-contained packages that users can install with a single command — no manual file copying required.

### Package Layout

A community module is a directory (or git repository) with this structure:

```
inventari-module-warranty-tracker/
├── module.yaml          ← unified top-level manifest (see below)
├── README.md
├── backend/             ← FastAPI module (copied to backend/app/modules/<name>/)
│   ├── __init__.py
│   ├── manifest.json    ← backend-specific manifest (required by module_registry)
│   ├── module.py
│   ├── router.py
│   ├── models.py
│   ├── migrations/      ← env.py + versions/ (this module's own Alembic chain)
│   ├── schemas.py
│   ├── services.py
│   ├── i18n/
│   │   ├── en.json
│   │   └── pl.json
│   └── tests/
└── frontend/            ← React module (copied to frontend/src/modules/<name>/)
    ├── module.ts
    ├── pages/
    │   └── IndexPage.tsx
    ├── components/
    ├── hooks/
    ├── i18n/
    │   ├── en.json
    │   └── pl.json
    └── types/
        └── index.ts
```

### `module.yaml` Schema

> **Licensing:** community modules may use any license, including proprietary — the
> copyright holder grants that permission explicitly under AGPL-3.0 §7 for modules that
> stay inside the public extension points. See [MODULE_LICENSING.md](MODULE_LICENSING.md).

```yaml
name: warranty_tracker          # must match backend/manifest.json "name"
version: "0.1.0"                 # your module's own maturity
inventari_min_version: "0.9.0"  # oldest platform this module is known to run on;
                                # a floor above the running platform refuses the install
author: "Your Name"
description: "Track warranties and service dates for your items."
license: "AGPL-3.0"             # any SPDX identifier, e.g. "MIT", "Proprietary"
homepage: "https://github.com/yourname/inventari-module-warranty-tracker"

requires: []                    # names of other modules this one depends on

components:
  backend: true                 # set to false for frontend-only modules
  frontend: true                # set to false for API-only modules
```

### Scaffold a new community module package

```bash
make new-community-module
# or
docker compose exec backend uv run python manage.py module new-community warranty_tracker --output /modules-workspace
```

This creates `./modules-workspace/warranty_tracker/` (the container sees it as
`/modules-workspace`; without `--output` the command writes into its current
directory inside the container) with all files pre-filled
and ready to edit — a directory git ignores and the backend container can see,
so the install below reaches it and `git add -A` here cannot take it.

### Install a community module

```bash
# From a local directory
docker compose exec backend uv run python manage.py module install /modules-workspace/warranty_tracker

# From a git repository — git sources require a pinned --rev
docker compose exec backend uv run python manage.py module install https://github.com/user/inventari-module-warranty-tracker.git --rev v1.2.0
```

The installer verifies the package signature **before a single file is
copied**, against the keys this deployment trusts
(`MODULE_SIGNING_PUBLIC_KEYS`, comma- or newline-separated
`key_id=<base64 public key>` entries in the backend environment /
`.env.example`; always give the id — a key listed without one is not
trusted). Three outcomes:

- **verified** — the package content matches a signature from a trusted
  key; the tracking record stores who signed and when it was verified.
- **unsigned** — no `module.sig` in the package. Installs only with the
  explicit `--allow-unsigned` switch: nobody vouched for the code, and it
  runs in-process with full access to the database and the filesystem.
- **invalid** — the content does not match what was signed, the signing
  key is not trusted, or the signature is unreadable. **Refused, and
  `--allow-unsigned` does not override it** — that switch accepts the
  absence of a vouch, never evidence against one.

After the copy, the installer runs the AST safety scan over the files and
imports the backend package. A package that fails either is refused and its
files are removed again (see *When the backend does not come back*).

As an author you sign with an Ed25519 key pair. Generate one once per
publishing identity — it writes the private key where the `module sign` step
reads it and prints the public key that installations list in
`MODULE_SIGNING_PUBLIC_KEYS` (see above):

<!-- modules-guide-check: keygen -->

```bash
# Generate a key pair (once per publishing identity): writes the private key
# file, prints the public key that installations trust. If the key file exists
# the command stops and leaves it alone: replacing a key would orphan every
# package signed with the old one.
docker compose exec backend uv run python -c "
import base64, os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
k = Ed25519PrivateKey.generate()
fd = os.open('/modules-workspace/my-ed25519.key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.fchmod(fd, 0o600)
os.write(fd, base64.b64encode(k.private_bytes(
    serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
)))
os.close(fd)
print('public key:', base64.b64encode(k.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)).decode())
"
```

Put the printed public key in
`MODULE_SIGNING_PUBLIC_KEYS=my-releases=<base64 public key>`, then sign the
package:

<!-- modules-guide-check: sign -->

```bash
docker compose exec backend uv run python manage.py module sign \
  /modules-workspace/warranty_tracker --key /modules-workspace/my-ed25519.key --key-id my-releases
```

Re-run `module sign` after every content change — a signature covers the
exact bytes signed. What is signed is what installs, file for file: the
same walk feeds both the digest and the copy (`tests/` and `__pycache__`
never ship, symlinks are refused). The walk also refuses a package
carrying executable code in a format the safety scan cannot read —
compiled bytecode (`.pyc`, `.pyo`) and native binaries (`.so`, `.pyd`,
`.dll`, `.dylib`): code ships as `.py` source, so both `module sign` and
`module install` refuse a package that holds bytes no scan report speaks
about.

What a signature covers is fixed by its **format**, which `module.sig`
names. `module sign` writes format 1:

```json
{
  "format": 1,
  "algorithm": "ed25519",
  "key_id": "my-releases",
  "signature": "<base64 Ed25519 signature>"
}
```

The Ed25519 signature is made over this text, UTF-8, each line ending in a
newline:

```text
inventari-community-module/1
name: <name from module.yaml>
version: <version from module.yaml>
sha256: <hex digest of the package>
```

The digest is a SHA-256 over the files the walk ships, in this order:
`module.yaml` first, then every file under `backend/` and then under
`frontend/` (a component switched off in `module.yaml` is skipped), each
tree sorted by path. Each file is fed in as its path relative to the
package root (forward slashes, UTF-8), a NUL byte, its length as 8 bytes
big-endian, its bytes, and a NUL byte. The walk leaves out `module.sig`,
every file outside `module.yaml` and the two component trees, every
`__pycache__` directory and every `tests/` directory inside a component,
and refuses symlinks and the executable formats listed above.

A change to any of these rules is a new format with a number of its own;
an installer keeps reading format 1 after a later format exists, so a
module signed today stays verifiable. An installer that meets a format it
does not know refuses the package as **invalid** and names the number —
the package was signed by a newer Inventari, and installing it needs that
version or a signature this one can read. A `module.sig` with no format
at all was written before formats existed and is refused the same way;
run `module sign` again.

The installer:
1. Parses `module.yaml`
2. Verifies the package signature, before any file is copied
3. Runs the install guards: the platform's minimum version, reserved names
   (see above), a module of that name not already installed and no existing
   directory of that name, required modules present, and the declared
   component directories present
4. Copies `backend/` → `backend/app/modules/<name>/`
5. Runs AST safety validation and imports the copied backend package (rolls
   back on failure)
6. Merges the identity fields from `module.yaml` (author, description,
   license, homepage) into the `manifest.json` that landed under
   `backend/app/modules/` in step 4 — that file is what the registry reads,
   so it is what the store shows. A module with no
   author stays unsigned; it is never labelled "Core Team".
7. Copies `frontend/` → `frontend/src/modules/<name>/`
8. Updates `community_modules.json` tracking file
9. Prints restart instructions

It finishes by printing the host commands that make the change take effect.
They are not the same on the two stacks, and the installer prints the ones for
the installation it ran on:

- **Development stack** (`docker-compose.yml`): `docker compose restart
  backend` and `docker compose restart frontend`. The checkout is bind-mounted
  into both containers, so the files are already in place; the restarts are
  what make module discovery and the Vite dev server see them.
- **Production stack** (`docker-compose.prod.yml`): `docker compose -f
  docker-compose.prod.yml restart backend`, then `docker compose -f
  docker-compose.prod.yml build frontend && docker compose -f
  docker-compose.prod.yml up -d frontend`. The backend's module directories
  are mounted, but the screens are baked into the frontend image — and that
  image is nginx, which has no npm to run the development command.

Both halves land because both compose files mount the module trees into the
backend container (`INVENTARI_FRONTEND_MODULES_DIR` names the frontend mount).
On a deployment, run the installer **inside the backend container**: it is the
one process that can reach the database, which `module upgrade` and
`module uninstall` need:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py module install \
  https://github.com/yourname/inventari-module-warranty-tracker.git --rev v1.2.0
```

That container's user (`appuser`, uid 1000) must be able to write both mounted
trees. A checkout owned by another user — `root` on a typical VPS — needs this
once, before the first install; it adds the group write bit and leaves the
owner alone:

```bash
docker compose -f docker-compose.prod.yml exec --user root backend sh -c 'chgrp -R appuser /app/app/modules /frontend-modules && chmod -R g+rwX /app/app/modules /frontend-modules'
```

An install that finds a tree unwritable stops before copying and prints the
same command; upgrade and uninstall stop the same way before touching the
installed files.

The production compose mounts `backend/app/modules` and
`frontend/src/modules` from the checkout and keeps the tracking file in the
`module_data` volume, so an install survives `docker compose up -d` and image
rebuilds; the next frontend build picks the screens up. A local directory
source has to be reachable inside that container (a git URL needs nothing
mounted).

An install that cannot reach the tree says so, records the module as having no
frontend, and the App Store then shows it as a module without an interface —
rather than switching on a module that leads nowhere.

### Upgrade a community module

```bash
docker compose exec backend uv run python manage.py module upgrade ./warranty_tracker
docker compose exec backend uv run python manage.py module upgrade \
  https://github.com/yourname/inventari-module-warranty-tracker.git --rev v0.2.0
```

This is the route from one version to the next. It verifies the package the
same way an install does, replaces the module's files (a file the new version
dropped does not survive), runs the module's own migrations, and **does not
touch the data** — the tables the module owns keep every row.

On a deployment the command runs in the backend container for the same reason
every module command does — the migrations need the database:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py module upgrade \
  https://github.com/yourname/inventari-module-warranty-tracker.git --rev v0.2.0
```

The command finishes by printing the restart/rebuild commands for the stack
it ran on (see the install section). Take them: the migrations have run and
the tracking file already names the new version, but the running backend
still serves the old code, the installation record moves on the restart (when
`on_upgrade` runs), and a production frontend image still carries the old
screens until it is rebuilt. Afterwards `module list`, the tracking file and
the `module_installations` row should all name the same version.

The `on_upgrade(old_version, context)` hook runs on the next backend restart,
from the new version's code, with the previously installed version as
`old_version`. It runs once per installation, not once per worker. Schema
changes belong in the module's migrations, which the command has already run;
the hook is for what a migration cannot express, such as rewriting stored
settings into the shape the new version reads.

A package that is not newer than what is installed is refused unless you pass
`--force`: re-deploying the same version and rolling back to an older one are
both legitimate, and neither should happen because a tag was wrong.

### Uninstall a community module

```bash
# Development stack
docker compose exec backend uv run python manage.py module uninstall warranty_tracker

# Production stack — the installation record lives in the database
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py module uninstall warranty_tracker
```

Like install and upgrade, it prints the restart/rebuild commands for the
stack it ran on: the files are gone from the mounted trees, but the running
backend still serves the module, and a production frontend still carries its
screens until the image is rebuilt.

**The data is kept.** Uninstalling removes the module's files, its tracking
entry and its installation record; the tables it owns stay as they are, so
installing the module again picks them up where they were. Before it asks
anything, the command prints what the uninstall leaves behind: rows in the
module's own tables, organizations that still list the module in
`enabled_modules`, audit entries, approval requests and approval workflows
naming it, inventory records and categories tagged with its name, webhook
endpoints subscribed to its events, notifications pointing at its screens, and
files under `<org>/<module>/` in the storage backend.

```bash
docker compose exec backend uv run python manage.py module uninstall warranty_tracker --drop-data
```

`--drop-data` runs the module's `on_uninstall` hook, whose default
implementation downgrades the module's migrations to base — `DROP TABLE` on
everything the module owns, for **every organization on this installation**.
It is confirmed separately by typing the word `data`, and it is not undone by
reinstalling: what comes back is an empty schema. `--force` skips that
confirmation — that is what it is for (unattended scripts cannot type), so an
unattended call with `--force --drop-data` really does drop everything, and
the summary line afterwards says honestly which of the two happened.

Note what `--drop-data` does *not* remove: everything in the report that is not
one of the module's own tables. Those rows and files outlive the uninstall
either way — now without the code that could read them.

### When the backend does not come back

`module install` and `module upgrade` import the package's backend before
they finish, the way the backend does on its next start, and refuse a package
that does not import — a typo in an import name included — with the error,
rolling the files back. `module validate` runs the same import and fails on
it. A module that breaks after its install anyway (a file edited in place, a
core upgrade that removed a name it imports) is rejected at startup and the
backend starts without it: the pre-flight check in the container log
(`db doctor`) and `module list` name the module and the reason, and nothing
of it runs until it is fixed and upgraded, or uninstalled.

If the backend still restarts in a loop after a module change, read the end
of its log — the pre-flight check prints what it found there. A restarting
container has no steady process for `docker compose exec` to enter, so run
the uninstall in a one-off container, past the entrypoint that refuses to
start:

```bash
docker compose logs --tail 80 backend
docker compose run --rm --no-deps -T --entrypoint uv backend \
  run python manage.py module uninstall warranty_tracker
docker compose restart backend

# Production stack
docker compose -f docker-compose.prod.yml run --rm --no-deps -T \
  --entrypoint python backend manage.py module uninstall warranty_tracker
```

The uninstall keeps the module's data, as always: fix the package and
install it again to pick the tables up where they were.

### View installed community modules

```bash
docker compose exec backend uv run python manage.py module list
# shows a Type column (core, official or cloud for modules this repository ships;
# community for everything else) and the source path
```

### Tracking file

Installed community modules are tracked in `community_modules.json` under the
backend's `data/` directory.

That directory is deployment state, not repository content, so it is ignored by
git — installing a module leaves the working tree clean and `git pull` has
nothing to conflict with. The development stack sees it at
`backend/data/community_modules.json`, because `backend/` is bind-mounted into
the container. The production stack mounts the `module_data` volume at
`/app/data` instead: the file survives `docker compose up -d`, recreates and
image rebuilds, and does not depend on the checkout's ownership on the host.
Read it with `docker compose -f docker-compose.prod.yml exec backend cat
/app/data/community_modules.json`. A registry left at the old path
(`backend/community_modules.json`) is still read once, and the next install
writes to the new one.

```json
{
  "modules": {
    "warranty_tracker": {
      "version": "0.1.0",
      "inventari_min_version": "0.9.0",
      "source": "./warranty_tracker",
      "installed_at": "2026-03-25T14:30:00Z",
      "has_backend": true,
      "has_frontend": true
    }
  }
}
```

This file is deployment state and is ignored by git — each deployment keeps its own record of what is installed.

### Why no rebuild is needed for discovery

Both discovery mechanisms are already auto-scanning:
- **Backend**: `module_registry.discover_modules()` scans `backend/app/modules/*/` on every startup
- **Frontend**: `import.meta.glob("../../modules/*/module.ts")` in `frontend/src/lib/moduleRegistry/moduleLoaders.ts` knows every module folder at build time and imports a module's code only when an organization uses it

Installing a community module simply places files in the right directories — discovery happens automatically on the next restart/rebuild.

---

## 🔑 Permissions Model

A module declares its permissions in **`manifest.json`** — the single declaration point. The backend registry picks them up at discovery, the roles admin UI renders them, and endpoints enforce them.

```json
"permissions": [
  "warranty:read",
  {
    "key": "warranty:approve",
    "label_key": "warranty:permissions.approve",
    "description_key": "warranty:permissions.approveDesc",
    "default_roles": ["manager"]
  }
]
```

A bare string is shorthand: it widens to a definition whose `label_key` is `<module>:permissions.<action>`.

**Rules the schema enforces:**

- Each key is `<module>:<action>`: one or more colon-separated segments, each lowercase letters, digits and underscores, starting with a letter.
- A permission object takes only `key`, `label_key`, `description_key` and `default_roles`; any other field is refused.
- Keys must sit in the module's **own namespace**. `warranty` cannot declare `admin:access` as its own — otherwise the RBAC matrix would offer an admin grant that looks like it belongs to a third-party module.
- A **core** key (`items:read`, `admin:access`, …) may still be listed, as a statement that the module depends on it. It is not republished in the module's catalog section; the system section already defines it.

**Enforcement** uses the existing dependency — nothing module-specific to build.

Mount the pair on the **module router**, not on each endpoint. Safe methods
need the read key, mutating ones the write key, and one line covers the
endpoints somebody adds next year — which is the half a per-endpoint guard
always loses:

```python
router = APIRouter(
    dependencies=[
        Depends(require_module('warranty')),
        require_read_write('warranty:read', 'warranty:write'),
    ]
)
```

**Copy this from `app/modules/example_widgets/router.py`** — the reference
module, and the shape most modules here follow: the router-level pair is in
`equipment`, `example_widgets`, `maker`, `purchase_orders`, `recipes`,
`shopping_lists`, `stock_takes` and `warehouse`. Some modules gate otherwise
(`webhooks` is admin-only on the router; `approvals` and `printing` guard
endpoint by endpoint), so read the module you copy from. Its
`app/modules/example_widgets/tests/integration/test_widgets_permissions.py` is
the matching half: a viewer
reads, is refused every write, and a member with no explicit role row still
writes, because `default_roles` hands the keys to the roles that already had
the access.

A narrower key — one action a role may take and its neighbours may not — is a
per-endpoint dependency on top of the router pair:

```python
if not current_user.has_permission('warranty:approve'):
    raise ForbiddenException(...)
# or, as a route dependency:
_: object = require_permission('warranty:approve')
```

The frontend has the other half of the same rule: **`useCanWrite('<module>')`
guards every write on the screen, not the first one**, and
`<ReadOnlyNotice module="<module>" />` says why the buttons are gone — a page
that hides its actions silently reads as broken rather than as a boundary.
`frontend/src/modules/example_widgets/pages/WidgetsPage.tsx` is the reference.
A gate the API enforces and the screen ignores is worse than no gate: the
reader fills the form to the end and meets the refusal at the submit.

Every key a module declares needs a place that enforces it — a string literal
handed to `require_permission`, either half of `require_read_write` or
`has_permission`. Otherwise the roles matrix shows a switch that restricts
nothing. For modules in this repository the architecture lint (`make lint`)
refuses such a key.

Admins bypass permission checks (`UserContextDTO.has_permission`), so an organization that has granted nothing is still administrable.

**`default_roles`** is applied when the module is enabled for an organization: the permission is added to that org's roles with matching names. Roles are **never created** — a name with no matching role grants nothing, rather than inventing authority as a side effect of switching a module on. In an org with no roles at all, the feature is admin-only until someone grants it in **Settings → Access & Roles**, which renders its columns from `GET /api/v1/roles/permission-catalog`, scoped to the modules that org has enabled.

Labels come from i18n via `label_key`, falling back to the raw key, so a module that ships no translation still renders a usable (if terse) column.

---

## ⚡ Module Lifecycle: Install vs Activate

Module installation writes files, then needs a restart (development) or a
frontend image rebuild plus a backend restart (production). Runtime
enable/disable is instant.

### 1. Installation (compile-time)
```bash
# Community module install
python manage.py module install ./my-module
# ...and, later, the same module at a newer version
python manage.py module upgrade ./my-module
```
- **Signature verified first** — the installer checks the package signature against the deployment's trusted keys before a single file is copied; an unsigned package installs only with the explicit `--allow-unsigned` switch (see ["Install a community module"](#install-a-community-module))
- Copies source files to `backend/app/modules/<name>/` and `frontend/src/modules/<name>/`
- Updates `community_modules.json` tracking file
- **Backend restart required** — `discover_modules()` runs at startup
- **Frontend restart or rebuild required** — Vite `import.meta.glob` picks up new `module.ts` when the dev server starts, and at build time in the production image; the installer prints the one that applies to the stack it ran on
- Installing over a tracked module is refused: `module upgrade` is the way
  across versions. (It used to point at `module uninstall` instead, which at
  the time dropped the module's tables — the documented upgrade path destroyed
  the data it was upgrading.)

The hooks that go with each step:

| Step | Hook | Default |
|---|---|---|
| First boot after an install | `on_install` / `on_install_async` | runs the module's migrations forward |
| First boot after a version bump | `on_upgrade(old_version, ctx)` / `on_upgrade_async(old_version, ctx)` | nothing — `module upgrade` has already run the migrations |
| `module uninstall --drop-data` | `on_uninstall` | downgrades the module's migrations to base (drops its tables) |

`on_install` and `on_upgrade` each run once per installation even when several
workers boot at the same time; the installation row is claimed first and locked
for the upgrade check. `on_upgrade_async` is awaited beside `on_upgrade` under
the same lock, for a reshape that needs the database.

### 2. Activation (runtime, per-organization)
- Admin enables/disables modules via the **App Store** (the `/apps` page, admin-only; Settings → Modules opens it)
- Stored in `organization.enabled_modules` column (JSON array)
- **Instant** — no restart needed. The backend checks enabled modules on every request.
- Dependent modules are checked at enable time (see "Dependency Enforcement" below)

### 3. Discovery (backend startup)
```
1. _registry_class.py scans backend/app/modules/*/ for manifest.json
2. Validates manifest via Pydantic schema (ModuleManifest)
3. AST safety check (forbidden imports/calls) — relaxations come from name-keyed tables in `app/core/module_safety.py`: `TRUSTED_SHIPPED_MODULES` (the in-repo module directories on the core-trust list: the `app.`-internal bans are lifted), `REPO_SHIPPED_MODULES` (shipped modules are exempt from the module import-surface rule) and `CORE_EXEMPTIONS` (per-module named exemptions, which also cover third-party imports — `printing`/`subprocess`, `webhooks`/`socket`); every module outside the tables meets the full ban list
4. Dependency check — modules with missing required modules are rejected
5. Instantiates BaseModule (or define_module() output)
6. Registers routes, interceptors, contribution points, schedules
```

### 4. Dependency Enforcement

Modules can declare `requires` in `manifest.json`:
```json
{ "name": "stats", "version": "0.5.0", "module_type": "core", "requires": ["items"] }
```

Dependencies are checked at three lifecycle points:
- **Discovery**: modules with missing required modules are rejected at startup
- **Enable**: admin cannot enable a module if its dependencies are not enabled
- **Uninstall**: cannot uninstall a module that other modules depend on

Modules in `ALWAYS_ON_MODULES` (`core`, `items`, `locations`, `categories`, `stats`, `printing`, `announcements`) are implicitly available and skipped during dependency checks.

---

## 📋 Module Capabilities

Capabilities are declared in `manifest.json` and read by the AST safety scan, which matches import statements against them by literal name. How much a module is exempted is decided by the name-keyed tables in `app/core/module_safety.py`: `TRUSTED_SHIPPED_MODULES` (the in-repo module directories on the core-trust list) lifts the `app.`-internal bans, `REPO_SHIPPED_MODULES` exempts the modules this repository ships from the module import-surface rule, and `CORE_EXEMPTIONS` grants named modules specific imports — including third-party ones (`printing`: `subprocess`, `os`; `webhooks`: `socket`).

> **⚠️ What the AST validator is, and is not.** It enforces *architecture* — which
> imports and calls a module may use — so that modules stay inside the contract
> and do not reach into core internals. **It is not a security sandbox.** Module
> code runs in-process with the same database and filesystem access as the core,
> and the scan matches imports by literal name rather than guarding resources.
> A module you install can do anything your server process can do
> ([ADR-019](docs/adr/ADR-019-modules-are-certified-not-sandboxed.md)).
>
> Practical consequence: treat installing a community module like adding a
> dependency to your own codebase, not like opening a document. Pin the revision
> (`module install <url> --rev <tag|commit>` — required for git sources, and the
> commit is recorded in `community_modules.json`), read the diff when you bump
> it, and install only from sources you would trust with your database.

> **See [`docs/MODULE_CAPABILITIES.md`](docs/MODULE_CAPABILITIES.md) for the full, verified capability table** (including the list of forbidden imports/calls that are rejected before the capability check, and the exact behaviour for unknown capability names). The summary below is repeated here for convenience.

### Available Capabilities

| Capability | Allows imports | Typical use |
|---|---|---|
| `network` | `requests`, `httpx`, `urllib` (not `urllib.request`, which is forbidden; see the note below) | API calls to external services |
| `filesystem` | `os`, `shutil`, `open()` | File I/O, temp files, CSV export |
| `process` | `sys` | Interacting with the Python runtime |
| `database` | `sqlalchemy`, `sqlmodel` | Direct DB access (rarely needed — prefer CoreAPI) |

> `socket`, `subprocess` and `urllib.request` are in `FORBIDDEN_IMPORT_PREFIXES` (`app/core/module_safety.py`) — the AST validator rejects them regardless of declared capabilities, for every module without a named exemption in `CORE_EXEMPTIONS`. Today that covers the in-repo `printing` (`subprocess`, `os`) and `webhooks` (`socket`); a new module cannot read this sentence as an allowance.

### Capability-specific imports

When the AST validator detects an import from a capability-gated module, it checks whether the capability is declared. Examples:

| Import | Required capability |
|---|---|
| `import requests` | `network` |
| `import httpx` | `network` |
| `import urllib` | `network` |
| `import os` | `filesystem` |
| `import shutil` | `filesystem` |
| `open(...)` call | `filesystem` |
| `import sys` | `process` |
| `import sqlalchemy` | `database` |

### Declaring capabilities

```json
{
  "name": "weather_widget",
  "version": "0.1.0",
  "module_type": "community",
  "inventari_min_version": "0.9.0",
  "capabilities": ["network", "filesystem"]
}
```

Run `python manage.py module validate --module my_module` to verify your capabilities are correctly declared.

Run `python manage.py module schema` to export the full JSON Schema for `manifest.json`.

---

## 🔧 CLI Commands

| Command | Description |
|---|---|
| `module create <name>` | Scaffold a new in-tree module |
| `module new-community <name> [-l pl]` | Scaffold a community module package (English catalogs; `-l` adds languages) |
| `module install <source>` | Install a community module from path or git URL |
| `module upgrade <source>` | Upgrade an installed community module to a newer package; keeps its data (`--rev` for git, `--allow-unsigned`, `--force`) |
| `module sign <source> --key <file> --key-id <id>` | Sign a community module package so installers can verify it (writes `module.sig`) |
| `module uninstall <name>` | Remove an installed community module |
| `module list` | Show all registered modules (table) |
| `module list --json` | Show all registered modules (JSON) |
| `module validate [--module <name>]` | Validate manifest + AST safety rules |
| `module smoke <name>` | Comprehensive smoke test on a single module |
| `module schema` | Export manifest.json JSON Schema to stdout |

---

## 📌 Versioning & CoreAPI Stability

The single source of truth for the platform version is the **README release section** (currently **Alpha v0.11.0**). `backend/pyproject.toml` and `frontend/package.json` mirror that version. A release carries the same number into `backend/uv.lock`, `frontend/package-lock.json`, `docs/api/openapi.json` and the README release section, so bump all of them together.

- **From 0.11:** contract DTOs, stable `core_api` namespaces, the manifest and webhook envelope have compatible-evolution promises. Stable surfaces follow the additive-only rule and a two-minor-release deprecation window; experimental surfaces may change in a minor release with release notes and migration instructions, without a window.
- The REST list and pagination envelopes, the error shape and refusal codes, and API keys are **stable from 0.11.0**; the rest of the REST API and the frontend module interface are **experimental in 0.11**. See the [Contracts Stability Policy](docs/subsystems/CONTRACTS_STABILITY.md) for the full surface map, namespace exceptions and guards. Backend facade stability does not imply frontend or HTTP stability.
- Module authors should re-run `manage.py module validate` after each platform upgrade.

### OpenAPI schema artifact

The full REST schema is committed at [`docs/api/openapi.json`](docs/api/openapi.json) — import it into Postman / Insomnia / Bruno to explore the API without running the backend. It is a maintained artifact: `make check-frontend` fails (`make check-openapi-fresh`) when it drifts from the live schema, so after endpoint or response-model changes regenerate it — the gate, not memory, keeps it current:

```bash
make generate-openapi
```

(Production runs do not expose `/openapi.json` — the committed artifact is the canonical export.)
