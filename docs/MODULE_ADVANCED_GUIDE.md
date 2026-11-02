# Inventari: Advanced Module Guide

Use this guide when your module needs to participate in a wider workflow:
validate an operation before it posts, react after it commits, schedule
background work or extend the data and screens of another module.

For a complete example, follow **Extending the warehouse** in this guide.
The [Lot certificates module](../examples/lot_certificates/README.md) adds
receipt fields, a posting check, a picking strategy and document-list
contributions through the warehouse's public interfaces.

Start with [Module Quick Start](../MODULE_QUICKSTART.md) if you are creating
your first package. The [module guide](../MODULES_GUIDE.md) explains ownership
and access to Core; the
[compatibility policy](subsystems/CONTRACTS_STABILITY.md) states which
extension points are stable.

---

## Lifecycle Hooks

Defined inside your `module.py` class that inherits from `BaseModule` (or via `define_module()`).

| Hook | When it fires | Typical use |
|---|---|---|
| `on_startup(context)` | **Every application restart** (backend boot) | Register event listeners, scheduled tasks, interceptors |
| `on_install(context)` | **Once per installation**, on the first boot that finds the module new to the system (not per organization, and not when it is enabled) | Create module-local DB tables, seed reference data |
| `on_enable(organization_id, context)` | **Every time** an organization toggles the module ON through the App Store toggle or a profile switch. Onboarding and the demo seed do not call it; they run `system_on_enable`, which seeds the categories and storage locations the module declares | Seed org-specific defaults (storage locations, categories) |
| `on_disable(organization_id, context)` | **Every time** an organization toggles the module OFF | Cleanup org-scoped resources, archive data |
| `on_upgrade(old_version, context)` | **First boot after the installed version changes** | Reshape stored data a migration cannot express |
| `on_upgrade_async(old_version, context)` | Same boot, when the reshape needs the database | Await the rewrite inside the upgrade |
| `on_uninstall(context)` | **Once ever** when the module is removed from the system | Drop module tables, purge data |

The table covers the hooks a module overrides at the lifecycle events. Three
more run at the same points: `on_install_async(context)` is the async variant
of `on_install`, `on_startup_async(context)` the async variant of `on_startup`,
and `on_modules_ready(context)` runs after every module's startup hooks, for
code that reads a catalogue other modules fill. The default `on_startup` calls
`register_services(container)` and `register_contributions()`; a module that
overrides `on_startup` without calling `super()` loses both, and the
interceptor wiring with them.

Every hook that takes an organization receives it as a `UUID`, the same type
the `core_api` methods take, so a hook passes it straight on instead of
parsing a string. `on_upgrade` and `on_upgrade_async` both run on the first
boot after the version changes, under one row lock, so a module that
overrides one of them pays nothing for the other — override
`on_upgrade_async` when the work has to be awaited, such as reading or
rewriting stored settings (for settings stored in the module's own
namespace, the per-organization pass in
[Module Settings](#module-settings) is the sanctioned way to do that
rewrite):

```python
class MyModule(BaseModule):
    async def on_upgrade_async(
        self, old_version: str, context: ModuleContext
    ) -> None:
        # For numeric major.minor.patch versions, compare numbers, not strings.
        if tuple(int(part) for part in old_version.split('.')) < (2, 0, 0):
            await context.migrate_settings(self.metadata.name, self._migrate)
```

```python
class MyModule(BaseModule):
    def on_install(self, context: ModuleContext):
        """Called once per installation, on the first boot that finds the module new."""
        super().on_install(context)  # keeps the default: the module's migrations

    def on_startup(self, context: ModuleContext):
        """Called every time the application starts up."""
        super().on_startup(context)  # keeps the default: contributions and interceptor wiring
```

> **Heads-up:** Routers and services do **not** have access to `ModuleContext`. If you need to emit events from an endpoint, call `core_api.events.emit_async(...)` (or `emit_transactional_async(db, ...)` when the event must commit with the write), and use `core_api.notifications` for in-app triggers.

### Using lifecycle hooks with `define_module()`

```python
from datetime import timedelta
from uuid import UUID

from app.core.module_sdk import ModuleScheduledTask, define_module

def _seed_defaults(org_id: UUID, ctx):
    """Called on module enable — seed org-specific data."""
    pass

def my_periodic_task():
    """Run the periodic task."""
    pass

module = define_module(
    router=router,
    seed=_seed_defaults,           # replaces on_enable
    schedules=[ModuleScheduledTask('cleanup', timedelta(hours=1), my_periodic_task)],
)
```

---

## Module Settings

A module stores per-organization settings in its own namespace of
`organization.settings`, written and read through `core_api.settings`:

```python
await core_api.settings.set_bulk_async(db, org_id, 'my_module', {'timeout': 30})
timeout = await core_api.settings.get_async(db, org_id, 'my_module', 'timeout')
```

`get_settings_schema()` (or `settings_schema=` in `define_module()`) declares
the settings shape. The module-settings write path validates the payload using
the keyword subset below. Unknown schema keywords are ignored, so do not rely
on them for validation. `core_api.settings.set_bulk_async` merges values and
stamps the version without validating the payload or encrypting secret values;
callers using it must ensure their values satisfy the schema and encrypt
secrets with `core_api.settings.encrypt_secret(module_name, value)` before writing them.

### The settings schema version

The settings **shape** — which keys exist and what they mean — carries its
own version, declared at the top of the schema. It is independent of the
module's version in `manifest.json`: the module version says which code is
installed, the schema version says which shape the stored data is in.

```python
def get_settings_schema(self) -> dict:
    return {
        'type': 'object',
        'version': 2,                       # this shape is version 2
        'properties': {
            'timeout': {'type': 'integer', 'default': 30},
        },
    }
```

A schema that declares no `version` is version 1. `version` must be a
positive integer; anything else is a `ContractViolationError`.

Every write stamps the stored blob with the schema version it was written
against, under the reserved key `__schema_version` (exported as
`SCHEMA_VERSION_KEY` from `app.core.settings_validator`). The stamp is core's
metadata about the blob, not module data:

- a schema may not declare a property named `__schema_version` — the name is
  reserved, at any nesting level;
- a payload that carries `__schema_version` is ignored, so a stored blob can
  be validated and written back as-is;
- `core_api.settings.get_async()` never returns it — the module reads its
  data only;
- the audit journal never shows it.

To read the version a blob was actually saved against — which is what a
migration needs — use:

```python
saved = await core_api.settings.get_schema_version_async(db, org_id, 'my_module')
```

A blob written before versioning existed has no stamp and reads as `0`.

### Migrating every organization's settings

`on_upgrade` runs once per installation, but settings are saved once per
organization — so a shape change needs a pass over every organization's
copy, each migrated from the version *it* was saved against. That pass is
`context.migrate_settings`, called from `on_upgrade_async`:

```python
class MyModule(BaseModule):
    def get_settings_schema(self) -> dict:
        return {
            'type': 'object',
            'version': 2,
            'properties': {'timeout': {'type': 'integer', 'default': 30}},
        }

    async def on_upgrade_async(
        self, old_version: str, context: ModuleContext
    ) -> None:
        def rename(org_id, from_version, settings):
            # from_version is this organization's stamp (0 = pre-versioning).
            if from_version < 2 and 'timeout_s' in settings:
                renamed = {k: v for k, v in settings.items() if k != 'timeout_s'}
                return {**renamed, 'timeout': settings['timeout_s']}
            return None

        await context.migrate_settings(self.metadata.name, rename)
```

The callback receives `(organization_id, from_version, settings)`.
`settings` is the organization's blob without the stamp; `from_version` is
the version it was saved against. Return the new settings, or `None` to keep
the data as it is — editing the given dict in place is honoured too. The
callback may be async.

Every organization whose blob is older than the schema's declared `version`
is migrated; blobs already at the declared version are skipped, so the pass
is safe to run again. Each migrated blob is stamped with the declared
version. The pass flushes only — the boot transaction commits it. Secrets
are stored encrypted and reach the callback as ciphertext: round-trip them
unchanged.

`core_api.settings.migrate_settings_async(db, module_name, migrate)` is the
same pass for code outside a hook.

### The validator's keyword contract

The root schema must be `{"type": "object"}`. Supported keywords:

| Keyword | Applies to | Meaning |
|---|---|---|
| `type` | any | `object`, `string`, `integer`, `number`, `boolean`, `array` |
| `properties` | object | named sub-schemas, validated recursively |
| `required` | object | keys the payload must carry |
| `additionalProperties` | object | `False` (default) refuses unknown keys, `True` lets them through |
| `enum` | any (when no `type`) | the value must be one of the listed ones |
| `minimum` / `maximum` | integer, number | inclusive numeric bounds |
| `minLength` / `maxLength` | string | length bounds |
| `items` | array | schema every element is validated against |
| `format: "secret"` | string | the module-settings write path encrypts the value; reads mask it |
| `default` | any | filled in on write when the key is neither sent nor saved |
| `version` | root | the settings shape version (see above) |
| `title`, `description`, `title_key`, `description_key` | any | labels for the settings form; `*_key` values are i18n keys |

Two refusals leave the validator. A payload that breaks the schema is a
reader's mistake: `SchemaValidationError`, carrying an i18n key the 400
envelope answers in the reader's language. A schema the validator cannot
read — an unsupported type, a bad `version`, a property named
`__schema_version` — is the module author's mistake:
`ContractViolationError`, in English, for the developer and the log.

---

## Event Bus (Pub/Sub)

Modules can listen to system events and emit custom events without tight coupling.

```python
from app.core.module_sdk import BaseModule, ModuleContext, SystemEvent

class MyModule(BaseModule):
    def on_startup(self, context: ModuleContext):
        super().on_startup(context)  # keeps the default contribution and interceptor wiring
        # Subscribe to a system event
        context.subscribe(SystemEvent.ITEM_USED, self._handle_use)

        # Subscribe to a custom event from another module
        context.subscribe("rental.reservation_created", self._handle_reservation)

    async def _handle_use(self, payload):
        print(f"Item used in org: {payload.organization_id}")

    async def some_action(self, context):
        # Emit a custom domain event (auto-scoped to tenant)
        await context.emit("my_module.action_done", {"detail": "value"})
```

**Convention:** Custom events use `"<module>.<event_name>"` format (e.g. `"rental.reservation_created"`, `"production.order_completed"`).

**Delivery semantics (since 2026-07):**

- **Production is stream-only and asynchronous.** `emit()` performs a single `XADD` to the Redis stream and returns immediately — handlers do **not** run in the emitting request's process. One consumer-group worker picks each message up and runs the subscribed handlers there.
- **Delivery is at-least-once, not exactly-once.** A worker that dies after a handler ran but before the ACK leaves the message pending, and the next reclaim pass runs the handlers again; a handler that raises, or outlasts the handler timeout, is retried with backoff and — if it keeps failing — parked as dead, and for an event that belongs to an organization its admins are alerted (an event of no organization is only recorded and logged). Write handlers to tolerate a re-run; an idempotent handler is the only safe shape. Do not rely on the handler running on the same node (or in the same request lifecycle) as the emitter.
- **No ordering guarantee** between different events, and no handler may assume request-scoped state (current user, request DB session) — handlers run in the consumer's background loop with their own DB session.
- **No Redis / Redis failure** is a conscious fail-open: events dispatch in-process only (other nodes miss them) and a warning is logged once per process. The fallback and the TESTING dispatch below log a failing handler; only stream deliveries are retried.
- **TESTING mode** keeps the legacy inline, synchronous dispatch with no stream, so unit/integration tests can `await emit(...)` and assert handler effects immediately.

**Available system events** (the `SystemEvent` members, imported from `app.core.module_sdk`): `ITEM_CREATED`, `ITEM_UPDATED`, `ITEM_DELETED`, `ITEM_MOVED`, `ITEM_USED`, `ITEM_DISPOSED`, `ITEM_TRANSFERRED`, `ITEM_DEACTIVATED`, `ITEM_STATUS_CHANGED`, `CATEGORY_CREATED`, `CATEGORY_UPDATED`, `CATEGORY_DELETED`, `STORAGE_CREATED`, `STORAGE_UPDATED`, `STORAGE_DELETED`, `ORGANIZATION_CREATED`, `ORGANIZATION_UPDATED`, `USER_REGISTERED`, `USER_JOINED_ORG`, `USER_LEFT_ORG`, `MODULE_ENABLED`, `MODULE_DISABLED`, `LABEL_SCANNED`, `LABEL_ASSIGNED`, `LABEL_BATCH_GENERATED`, `LABEL_BATCH_EXPORTED`, `PARTNER_ACTIVATED`, `PARTNER_DEACTIVATED`.

Module-owned events are **not** in that enum. For example, `equipment.checkout` and `equipment.checkin` live in `app.modules.equipment.events`, `document.*` in `app.modules.warehouse.events`, and `purchase_order.*` and `receipt.created_from_po` in `app.modules.purchase_orders.events`; each module registers its payload contract in its `on_startup` (`core_api.events.register_payload`). A subscriber names another module's event by its string and never imports that module's enum.

---

## Data Interceptors (Modifying Data in Flight)

Interceptors allow you to mutate data before and after it is saved. Three interceptor types are available.

Interceptors run only for organizations that have your module enabled — an organization that switched the module off is not affected by its hooks, exactly as it is not served by its routes. Interceptors registered from outside `app.modules.<name>.*` are not gated this way.

### `ItemInterceptor` hooks

| Hook | When | Can modify |
|---|---|---|
| `before_create(data, context)` | Before item is created | `data` dict (name, barcode, meta_data, etc.) |
| `after_create(item_id, data, context)` | After the write is flushed, pre-commit (same transaction) | Read-only (side effects only) |
| `before_update(item_id, changes, context)` | Before item is updated | `changes` dict |
| `after_update(item_id, changes, context)` | After the write is flushed, pre-commit (same transaction) | Read-only |
| `before_delete(item_id, context)` | Before item is deleted | Raise `InterceptorError` to abort |
| `before_purge(item_id, context)` | Before an archived item is permanently purged; the soft delete keeps `before_delete` | Raise `InterceptorError` to abort |
| `after_delete(item_id, context)` | After the write is flushed, pre-commit (same transaction) | Read-only |
| `before_consume(item_id, quantity, context) -> None` | Before item quantity is reduced | Raise `InterceptorError` to abort; cannot modify `data` |
| `after_consume(item_id, quantity, context) -> None` | After the write is flushed, pre-commit (same transaction) | Read-only (side effects only) |
| `before_discard(item_id, quantity, context) -> None` | Before item is discarded | Raise `InterceptorError` to abort; cannot modify `data` |
| `after_discard(item_id, quantity, context) -> None` | After the write is flushed, pre-commit (same transaction) | Read-only (side effects only) |

### `StorageInterceptor` hooks

| Hook | When |
|---|---|
| `before_create(data, context)` | Before storage is created |
| `after_create(storage_id, data, context)` | After the write is flushed, pre-commit (same transaction) |
| `before_update(storage_id, changes, context)` | Before storage is updated |
| `after_update(storage_id, changes, context)` | After the write is flushed, pre-commit (same transaction) |
| `before_delete(storage_id, context)` | Before storage is deleted |
| `after_delete(storage_id, context)` | After the write is flushed, pre-commit (same transaction) |

> **Note on `after_*` hooks:** they run *after the write has been flushed but
> **before commit***, inside the same DB transaction as the operation (services
> only `flush()`; the commit belongs to whoever owns the session — the request
> teardown for an API call, the job itself for a background item import). They are
> read-only — do not use them for external side effects (webhook / email /
> print / SMS). Use the EventBus for those (ADR-007); an event that must agree
> with the write goes through the outbox (`core_api.events.emit_transactional_async`), which commits
> or rolls back with the transaction.

### `CategoryInterceptor` hooks — same shape as `StorageInterceptor`.

### Example

```python
from app.core.module_sdk import (
    BaseModule,
    ItemInterceptor,
    ModuleContext,
    interceptor_pipeline,
)

class EquipmentInterceptor(ItemInterceptor):
    priority = 50

    async def before_create(self, data: dict, context: ModuleContext) -> dict:
        if data.get("context_tag") == "equipment":
            data.setdefault("meta_data", {})
            data["meta_data"]["equipment"] = {"status": "available"}
        return data

    async def before_update(self, item_id, changes: dict, context: ModuleContext) -> dict:
        return changes  # abstract in the base class, so every item interceptor defines it

    async def after_create(self, item_id, data: dict, context: ModuleContext):
        pass  # e.g. enqueue a background job

class MyModule(BaseModule):
    def register_contributions(self):
        interceptor_pipeline.register_item_interceptor(EquipmentInterceptor())
```

To abort an operation, raise `InterceptorError` from a `before_*` hook:

```python
from app.core.module_sdk import InterceptorError

async def before_delete(self, item_id, context):
    raise InterceptorError("Cannot delete equipment that is checked out")
```

### Contribution points for interceptors

Register interceptors in `register_contributions()` using these points:

| Point | Method |
|---|---|
| `item_interceptors` | `interceptor_pipeline.register_item_interceptor(instance)` |
| `storage_interceptors` | `interceptor_pipeline.register_storage_interceptor(instance)` |
| `category_interceptors` | `interceptor_pipeline.register_category_interceptor(instance)` |

### Using interceptors with `define_module()`

```python
from app.core.module_sdk import define_module

module = define_module(
    router=router,
    interceptors=[EquipmentInterceptor()],
)
```

---

## Background Tasks (Scheduler)

Need to run periodic jobs? Declare them with `schedules=` on
`define_module()`; the module's name is attached for you and the task is
registered when the module starts:

```python
from datetime import timedelta
from app.core.module_sdk import ModuleScheduledTask, define_module

module = define_module(
    router=router,
    schedules=[
        ModuleScheduledTask('daily_cleanup', timedelta(hours=24), daily_cleanup_task)
    ],
)
```

The scheduler behind it (`app.core.scheduler.task_scheduler`) is Core's own:
a module in this repository may call it from `on_startup`, but a module
installed from outside may import only `app.core.module_sdk`,
`app.core.public_api` and `app.core.contracts` (plus its own package, and the `<module>_api` of a shipped module it lists under `requires`), so `schedules=` is its way
in.

---

## Extending the warehouse: a worked example

A warehouse built for one customer is a module on top of Warehouse.
[`examples/lot_certificates`](../examples/lot_certificates/) is such a module,
complete: every received lot carries the number of its certificate, a receipt
is not booked while that certificate is not on file, a pick walks zone by zone
with the heaviest lines first, and the documents list shows the certificates
and filters by them. It is a community module like any other — it imports the
platform through `app.core.module_sdk`, `app.core.contracts`,
`app.core.public_api` and the warehouse's public API, and its screens through
`@/module-sdk` — and it is the test that keeps the seams working: the backend
suite installs it with `module install` (unsigned, outside the trusted set,
the safety scan on) and drives every seam through the warehouse's own doors
(`backend/app/modules/warehouse/tests/integration/test_the_guide_example_module.py`),
and `make e2e-example-module` walks a receipt and a pick through the browser
with it enabled. The code blocks below are the module's own files; the same
test fails when one of them and this page say different things.

Why the module plugs into seams rather than subclassing the warehouse is the
paragraph [MODULES_GUIDE.md](../MODULES_GUIDE.md) opens its "Extending
another module" section with.

### What it plugs in, and where

| Seam | What the module does with it | In the package |
|---|---|---|
| A field of its own on a line — `meta_data` ([Pattern 4](subsystems/CROSS_MODULE_EXTENSION.md)) and the form slots | the certificate number, under the module's name on each receipt line | `examples/lot_certificates/frontend/components/CertificateField.tsx`, `CertificateOnLine.tsx` |
| A pre-post check ([Pattern 6](subsystems/CROSS_MODULE_EXTENSION.md)) | at confirmation, no lot without its number; at posting, no certificate that is not on file | `examples/lot_certificates/backend/seams.py` `require_certificates` |
| A pick order ([Pattern 7](subsystems/CROSS_MODULE_EXTENSION.md)) | zone by zone, the heaviest line of each zone first | `examples/lot_certificates/backend/seams.py` `by_zone_then_weight` |
| A documents filter, column and action ([FRONTEND_MODULE_GUIDE.md](FRONTEND_MODULE_GUIDE.md), "Contributions to the warehouse documents") | a "certified lots" chip answered on the server, a certificate column on History and on Documents, a "file the certificates" button on the document | `examples/lot_certificates/backend/seams.py` `certified`, `examples/lot_certificates/frontend/module.ts` |
| A table and migration chain of its own | the register of certificates on file, and the endpoint that files them | `examples/lot_certificates/backend/models.py`, `examples/lot_certificates/backend/migrations/`, `examples/lot_certificates/backend/router.py`, `examples/lot_certificates/backend/certificates.py` |

The manifest lists `"requires": ["warehouse"]` (and `module.yaml` the same):
that is what lets the install-time scan open
`app.modules.warehouse.warehouse_api` to a module the repository does not
ship. Without it the import is refused like any other reach outside the SDK.

### Backend: the seams

The certificate number a lot arrived with is a fact about *that receipt line*,
so it lives on the line, in its `meta_data` under the module's name
(`{"lot_certificates": {"number": "…"}}`). The pre-post check reads it at
confirmation and refuses a lot without one; at posting it asks the module's
own register whether that certificate is on file. The one-step post asks
both stages in one transaction, so a refusal at either leaves nothing
written. Everything the module plugs in is registered in one function, called
at import:

<!-- example-file: backend/seams.py -->
```python
"""What this module plugs into the warehouse, and nothing else.

Four seams, each registered through ``warehouse_api`` (the manifest's
``"requires": ["warehouse"]`` is what lets a module from outside import it):

- a **required field**: a receipt line with a lot is not confirmed without the
  number of its certificate, kept on the line under this module's name;
- a **receiving rule**: a lot is not booked while that certificate is not on
  file in this module's own register;
- a **pick order**: zone by zone, the heaviest lines of each zone first;
- a **filter** of the documents list: the documents with a lot whose
  certificate is on file.

The module keeps no copy of a document and overrides no warehouse code: the
line's field is the warehouse's ``meta_data``, the refusal is a pre-post check
inside the warehouse's own posting, the walk is a strategy the organization
picks in the warehouse settings.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    DocumentFilterDTO,
    DocumentToPostDTO,
    PickOrderLineDTO,
    PickOrderLocationDTO,
)
from app.core.module_sdk import InterceptorError, get_module_error_message
from app.core.public_api import core_api
from app.modules.warehouse.warehouse_api import warehouse_api

from .certificates import all_numbers_on_file_async, numbers_on_file_async
from .models import NUMBER_MAX_LENGTH

MODULE = 'lot_certificates'

#: The name the organization picks in the warehouse settings, offered there
#: under ``lot_certificates:pickOrderStrategies.by_zone_then_weight``.
PICK_ORDER = 'by_zone_then_weight'

#: The documents-list filter, sent by the list as ``lot_certificates:certified``.
FILTER = 'certified'


def certificate_number(meta_data: dict[str, Any]) -> str | None:
    """The number this module wrote on a line, or None when it wrote none.

    The module reads its own key and only its own key. A blank number is
    none; any other is read as written, the same way by the rule, the
    register and the filter, so none of them calls a lot certified that
    another does not.
    """
    number = meta_data.get(MODULE, {}).get('number')
    if isinstance(number, str) and number.strip():
        return number
    return None


async def require_certificates(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> None:
    """Refuse a receipt whose lots are not certified.

    At ``confirm``: every line with a lot names its certificate, in a number
    the register can file. At ``post``:
    every certificate named is on file. The one-step post asks both, inside
    one transaction, so a refusal at either leaves nothing written.
    """
    if document.type != 'IN':
        return None
    lots = [line for line in document.lines if line.batch_number]
    for line in lots:
        number = certificate_number(line.meta_data)
        if number is None:
            raise InterceptorError(
                get_module_error_message(
                    MODULE, 'number_missing', lot=line.batch_number
                ),
                error_code='CERTIFICATE_NUMBER_MISSING',
            )
        if len(number) > NUMBER_MAX_LENGTH:
            raise InterceptorError(
                get_module_error_message(
                    MODULE,
                    'number_too_long',
                    lot=line.batch_number,
                    limit=NUMBER_MAX_LENGTH,
                ),
                error_code='CERTIFICATE_NUMBER_TOO_LONG',
            )
    if document.stage != 'post':
        return None
    named = {certificate_number(line.meta_data) or '' for line in lots}
    absent = sorted(named - await numbers_on_file_async(db, org_id, named))
    if absent:
        raise InterceptorError(
            get_module_error_message(
                MODULE, 'certificate_not_on_file', number=absent[0]
            ),
            error_code='CERTIFICATE_NOT_ON_FILE',
        )
    return None


def _zone(line: PickOrderLineDTO) -> PickOrderLocationDTO | None:
    """The place the line's shelf stands in — the shelf itself at the top."""
    path = line.location_path
    if len(path) >= 2:
        return path[-2]
    return path[0] if path else None


async def by_zone_then_weight(
    db: AsyncSession, org_id: UUID, lines: list[PickOrderLineDTO]
) -> Sequence[PickOrderLineDTO]:
    """Walk zone by zone; inside a zone take the heaviest line first.

    Zones follow the numbers the warehouse gave them, then their code and
    name. A line's weight is its product's weight times its quantity, in the
    reference unit of the product's weight unit; a product nobody weighed
    weighs nothing and comes last in its zone. Lines with no shelf come last.
    """
    template_ids = sorted(
        {line.product_template_id for line in lines if line.product_template_id}
    )
    templates = await core_api.product_templates.get_many_async(
        db, org_id, template_ids
    )

    def weight(line: PickOrderLineDTO) -> Decimal:
        template = (
            templates.get(line.product_template_id)
            if line.product_template_id
            else None
        )
        if template is None or template.weight_value is None:
            return Decimal(0)
        factor = template.weight_uom.factor if template.weight_uom else Decimal(1)
        return Decimal(str(template.weight_value)) * factor * line.quantity

    def key(line: PickOrderLineDTO) -> tuple[Any, ...]:
        zone = _zone(line)
        if zone is None:
            return (True, True, 0, '', '', Decimal(0))
        return (
            False,
            zone.sequence is None,
            zone.sequence or 0,
            zone.short_code or '',
            zone.name or '',
            -weight(line),
        )

    return sorted(lines, key=key)


async def certified(db: AsyncSession, org_id: UUID) -> DocumentFilterDTO:
    """The documents with a line whose certificate is on file.

    What the receiving rule asks at posting: a blank number, or one nobody
    filed, does not make a lot certified. Every number on file is one
    fragment; a register of thousands would want a narrower question.
    """
    numbers = await all_numbers_on_file_async(db, org_id)
    return DocumentFilterDTO(line_meta_data=[{'number': n} for n in numbers])


def register_seams() -> None:
    """Plug the module into the warehouse.

    Called once at import. Registering again replaces the same entries, so a
    reload — or a test that put something else under this name — is undone
    by calling it again.
    """
    warehouse_api.register_pre_post_check(MODULE, require_certificates)
    warehouse_api.register_pick_order_strategy(MODULE, PICK_ORDER, by_zone_then_weight)
    warehouse_api.register_document_filter(MODULE, FILTER, certified)
```

A confirm of a receipt whose lot line has no number answers 422 with
`detail.code` `CERTIFICATE_NUMBER_MISSING` and the module's own sentence (its
`backend/i18n/<lang>.json`, keys at the top level); a posting of one whose
certificate is not on file answers `CERTIFICATE_NOT_ON_FILE`, and nothing is
booked. The number can still be filled in after the document was created,
until it is posted: the document page's line slot gets `saveMetaData`, which
calls `PUT /warehouse/documents/{id}/lines/{line_id}/meta-data/lot_certificates`
and replaces the module's key on that line (and only it); a backend caller has
`warehouse_api.set_module_meta_data_async` for the same.

A field a module adds is free text to the warehouse, so the module bounds it
itself. A number longer than the register's column is refused at
confirmation (`CERTIFICATE_NUMBER_TOO_LONG`) and at the filing endpoint
(422), and the screens' inputs stop at the same length. And every reader of
the number reads it the same way — blank is none, anything else as written —
so the `certified` filter keeps exactly the lots the rule would book: those
whose number is on file, not those that merely carry one.

### A pick order of its own

`warehouse_api.register_pick_order_strategy(module, name, strategy)` claims a
way of walking the warehouse while picking — the seam a module reaches for
when the order the floor works in is its customer's own.
The strategy takes `(db, org_id, lines)` and returns **those same lines in
pick order**; each is a `PickOrderLineDTO` from `app.core.contracts` carrying
the line's product, quantity, the batch it plans from (`lot_name`), the shelf
it is taken from and that shelf's path (the walk-in: the zone before the
shelf). Above, `by_zone_then_weight` takes the place each shelf stands in as
its zone, walks the zones in their numbered order and, inside a zone, the
heaviest line first — the weight read from the product through
`core_api.product_templates`, one read for the whole session.

The organization chooses the strategy in the warehouse settings, where every
registered name is offered with the label the owning module's catalogue gives
it: the settings look up `<module>:pickOrderStrategies.<name>`, so this
example owes the catalogue key `lot_certificates:pickOrderStrategies.by_zone_then_weight`
in its frontend `en.json` (and in any other language it ships). The
default walk — `location_sequence`, the order the locations are numbered — is
registered the same way and is what runs when nothing is chosen, when the
chosen name answers no strategy, or when the module behind it is switched off
for the organization: a disabled module costs the organization its walk, never
a session that will not start.

### Frontend: the field, the column, the filter and the action

<!-- example-file: frontend/module.ts -->
```ts
import { lazy } from "react";
import { FileCheck } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/module-sdk";
import { MODULE, certificateNumbers, fileCertificates } from "./certificates";

// Translations need no registration: the module's `i18n/<lang>.json` is
// picked up as the `lot_certificates` namespace.
moduleRegistry.register({
  name: MODULE,
  // No screen of its own: everything this module shows is on the
  // warehouse's screens, through the seams below.
  routes: [],
  slots: [
    {
      slot: "document_line_form_extra",
      component: slotComponent(
        lazy(() => import("./components/CertificateField")),
      ),
    },
    {
      slot: "document_detail_line_extra",
      component: slotComponent(
        lazy(() => import("./components/CertificateOnLine")),
      ),
    },
  ],
  documentColumnContributors: [
    {
      key: "certificate",
      label: `${MODULE}:column.certificate`,
      hasValue: (doc) => certificateNumbers(doc).length > 0,
      render: (doc) => certificateNumbers(doc).join(", "),
    },
  ],
  // Answered on the server by the filter `seams.py` registers as `certified`.
  documentFilterContributors: [
    { key: "certified", label: `${MODULE}:filter.certified` },
  ],
  documentActionContributors: [
    {
      key: "file",
      label: `${MODULE}:action.file`,
      icon: FileCheck,
      // A receipt not yet booked that names certificates: what the
      // receiving rule waits for before the goods are booked.
      isAvailable: (doc) =>
        doc.type === "IN" &&
        ["DRAFT", "CONFIRMED"].includes(doc.status) &&
        certificateNumbers(doc).length > 0,
      run: async (doc) => {
        const filed = await fileCertificates(certificateNumbers(doc));
        return filed.length > 0
          ? `${MODULE}:action.filed`
          : `${MODULE}:action.alreadyOnFile`;
      },
    },
  ],
});
```

The field under every receiving line of the desktop Receive sheet and of the
document form (a phone's Receive counts its goods on the receiving session
instead) — the courtesy beside the check's guarantee: the reader hears about
a missing number before the server is asked.

<!-- example-file: frontend/components/CertificateField.tsx -->
```tsx
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Input, ReadableError } from "@/module-sdk";
import type { SlotDataMap } from "@/module-sdk";
import { MODULE, NUMBER_MAX_LENGTH, certificateNumber } from "../certificates";

/**
 * The certificate number under every received line with a lot.
 *
 * The value goes on the line, under this module's name, and travels with the
 * document. The pre-post check is the guarantee — a script posts without this
 * field — so this is the courtesy: the reader hears about a missing number
 * before the server is asked.
 */
export default function CertificateField({
  data,
}: {
  data: SlotDataMap["document_line_form_extra"];
}) {
  const { t } = useTranslation(MODULE);
  const { line, setMetaData, registerBeforeSubmit } = data;
  const applies = data.documentType === "IN" && Boolean(line.batchNumber);
  const number = certificateNumber(line.metaData);

  useEffect(() => {
    if (!applies || number) return undefined;
    return registerBeforeSubmit(() => {
      throw new ReadableError(
        t("field.missing", { lot: line.batchNumber ?? "" }),
      );
    });
  }, [applies, number, line.batchNumber, registerBeforeSubmit, t]);

  if (!applies) return null;
  return (
    <Input
      label={t("field.label", { lot: line.batchNumber ?? "" })}
      aria-required
      maxLength={NUMBER_MAX_LENGTH}
      value={String(line.metaData[MODULE]?.number ?? "")}
      onChange={(event) =>
        setMetaData(
          MODULE,
          event.target.value ? { number: event.target.value } : null,
        )
      }
    />
  );
}
```

What the warehouse's document screens give each of its four slots:

| Slot | Where | Receives |
|---|---|---|
| `document_form_extra` | Receive, Issue and the document form, among the document-level fields | `action`, `documentType`, `partnerId`, the draft's `lines`, `metaData`, `setMetaData`, `registerBeforeSubmit` |
| `document_line_form_extra` | Under each line of Receive (desktop only: a phone counts its goods on the receiving session instead), Issue and the document form (desktop and phone) | `action`, `documentType`, the `line` (with its `metaData`), `setMetaData`, `registerBeforeSubmit` |
| `document_detail_line_extra` | The document page, under each line | `documentId`, `documentStatus`, the `line` (with its `metaData`), `saveMetaData` |
| `document_detail_extra` | The document page, below lines and totals | `documentId`, `documentStatus`, `metaData`, `saveMetaData` |

Four behaviours to rely on:

- **A field of the document goes on the document.** `setMetaData(module,
  values)` puts your values under your module's name on the line (or, in
  `document_form_extra`, on the document) and they are sent with it — on a
  post, on a draft saved for later, and on every save of an edited draft,
  which sends back the fields of every module. `null` removes your key.
- **A record of your own saves in a callback.** When the value belongs in your
  module's tables rather than on the document, save it from a
  `registerBeforeSubmit` callback: the callbacks run in order before the
  screen posts or saves, and one that throws stops the send and shows its
  message — throw a `ReadableError` with a sentence for the reader. Return
  the function it gives back from your effect, so a removed line takes its
  callback with it.
- **The check is the guarantee, the field is the courtesy.** A script or
  another client posts without your field; only the pre-post check stops
  them. The field just lets the person fix the problem before the server
  says no.
- **Corrections carry the field.** A correction, an undo, a return and a
  backorder copy `meta_data` from the document they continue, so a check
  that asks for the field on those finds it there.

---

## See Also

- [MODULE_QUICKSTART.md](../MODULE_QUICKSTART.md) — 5-minute quickstart (entry point)
- [MODULES_GUIDE.md](../MODULES_GUIDE.md) — full reference, CoreAPI & ecosystem overview
