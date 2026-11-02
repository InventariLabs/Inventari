# Cross-Module Extension Guide

How modules interact with each other and with Core data without creating tight
coupling. **Read this before building a module that needs data from another
module.**

---

## The Golden Rule

**Modules must never import another module's models, services, or internal
helpers.** Cross-module interaction goes through one of the documented
patterns below. The architecture linter enforces this in CI.

---

## Pattern 1: CoreAPI (read/write Core data)

**When:** Your module needs to read or modify Core entities (Items, Locations,
Categories, Partners, Stock, etc.).

**How:** Import only the public facade:

```python
from app.core.public_api import core_api

async def my_feature(db, org_id, item_id):
    item = await core_api.items.get_async(db, org_id, item_id)
    await core_api.items.update_quantity_async(
        db, org_id, item_id, new_qty, user_id=user_id
    )
```

**Rules:**
- Never import `app.models` or `app.database` in `router.py` or `module.py`.
- Over 30 namespaces available (items, stock, locations, partners, valuation, email, etc.).
- See `docs/subsystems/CORE_API.md` for the full method reference.

---

## Pattern 2: EventBus (react to another module's lifecycle)

**When:** Your module needs to perform a side effect when something happens in
another module (e.g., "when an item is consumed, send a webhook").

**How:** Subscribe to a system event from your module's `on_startup(context)`.
The handler runs asynchronously after the original operation commits.

```python
from app.core.module_sdk import BaseModule, SystemEvent

class MyModule(BaseModule):
    def on_startup(self, context) -> None:
        super().on_startup(context)

        async def on_item_used(payload):
            # The handler receives the payload itself (ItemQuantityEventPayload:
            # organization_id, item, quantity, user_id) — immutable, so do NOT
            # mutate Core data here. `item` is the item as a dict.
            await send_notification((payload.item or {}).get('id'))

        context.subscribe(SystemEvent.ITEM_USED, on_item_used)
```

**Rules:**
- Event handlers **cannot mutate** the entity that triggered the event — the
  transaction is already committed.
- Handler failures are logged and do **not** affect the original operation.
- 28 system events defined (`SystemEvent`); module-owned events live in the modules. The `event_bus.subscribe(event, callback)`
  method (not a decorator) is the low-level API; in modules, prefer
  `context.subscribe(event, handler)` from `ModuleContext` inside `on_startup`.
- See `SystemEvent` in `app.core.module_sdk` for the catalog; its members are
  frozen by the contracts snapshot, so one cannot disappear unnoticed.
- **Need to validate or block an operation instead?** Use Interceptors
  (see ADR-007), not the event bus.

---

## Pattern 3: Polymorphic Sidecar (annotate another module's records)

**When:** Your module needs to attach typed data or state to a record owned by
another module — **without adding a column to that module's table.**

**Reference implementation:** the `approvals` module.

The `approvals` module lets any other module request approvals for its
operations. It does **not** add an `approval_status` column to the target
table. Instead, it uses a **polymorphic association**:

```python
class ApprovalRequest(Base):
    target_type: Mapped[str]        # "equipment_checkout", "document", ...
    target_id: Mapped[uuid.UUID]    # ID of the target record
    # NOTE: No ForeignKey to the target table! Polymorphic, no DB-level FK.
    status: Mapped[str]
    meta_data: Mapped[dict | None]
```

The providing module (`approvals`) exposes a stable API:

```python
from app.modules.approvals.approvals_api import approvals_api

# Check and block if approval is pending (async — always await):
await approvals_api.check_and_block(db, org_id, "your_module", target_id)

# Request a new approval (async — always await):
await approvals_api.request_approval(
    db, org_id, "your_module", target_id, user_id
)
```

**Rules:**
- `target_type` + `target_id` form a polymorphic link — **no foreign key** to
  the target table. This keeps modules decoupled at the DB level.
- The target module decides **when** to call `check_and_block()` (the "when"
  is business logic; the approvals module handles the "how").
- If the providing module is disabled, its API methods are safe to call
  (graceful degradation — no-op or sensible default).

**When to use sidecar vs. meta_data (Pattern 4):**
- Sidecar: the annotation is structured, queryable, has its own lifecycle
  (e.g., approval state machine, audit trail).
- meta_data: the annotation is a simple key-value enrichment on a Core entity,
  or a field of your own on a warehouse document or line.

---

## Pattern 4: `meta_data` JSONB (enrich Core entities and documents)

**When:** Your module needs to add custom fields to an `Item`, or to a
warehouse document or one of its lines.

**How:** Write under your module's namespace in the shared `meta_data` JSONB
column. A module writes its key on three records: `Item`, and the warehouse's
`Document` and `DocumentLine`. Neither `StorageLocation` (which has `settings` and
`warehouse_config`) nor `Organization` (which has `settings`) exposes a
`meta_data` column.

```python
# ✅ Good — namespaced
await core_api.items.update_meta_data_async(
    db, org_id, item_id, namespace='equipment',
    data={'serial_number': 'SN-123', 'warranty_until': '2027-01-01'}
)

# ❌ Bad — flat keys pollute shared space
item.meta_data['serial_number'] = 'SN-123'
```

### A field of your own on a document or a line

This is the way to add a field to a warehouse document — a certificate
number, a customs code, a quality grade — without a column on the warehouse's
tables and without a fork. It has three parts:

- **Storage.** `meta_data` on the document and on each line,
  `{'<your_module>': {...}}`. The documents API refuses a top-level value
  that is not an object under a module's name. A create or update payload
  carries it (`DocumentCreate.meta_data`, each line's `meta_data`; an update
  replaces it like the lines it carries).
  `PUT /warehouse/documents/{id}/meta-data/{module}` and
  `PUT /warehouse/documents/{id}/lines/{line_id}/meta-data/{module}` replace one
  module's key and leave the others alone (`{}` removes it); from the
  backend, `warehouse_api.set_module_meta_data_async(db, org_id, doc_id, module,
  values, user_id, line_id=None)` does the same in the caller's
  transaction. Writes are open until the document is completed or
  cancelled. A correction (and so an undo), a return and a backorder copy
  `meta_data` from the document they continue.
- **Screen.** The `document_form_extra` and `document_line_form_extra` slots
  render on Receive, Issue and the document form; they hand your component
  the document's or the line's `metaData` and a `setMetaData(module, values)`
  that writes back into the form, so the value is sent with the document.
  On the document page, `document_detail_line_extra` and
  `document_detail_extra` show the `metaData` and hand a `saveMetaData` that
  writes it to the saved document at once, through the routes above. See [FRONTEND_MODULE_GUIDE.md](../FRONTEND_MODULE_GUIDE.md).
- **Rule.** Your pre-post check (Pattern 6) receives `meta_data` on
  `DocumentToPostDTO` and on each of its lines, and refuses a confirm or a
  posting whose required field is empty.

A worked example — a certificate number required on every receipt line of a
lot — is in [MODULE_ADVANCED_GUIDE.md](../MODULE_ADVANCED_GUIDE.md),
"Extending the warehouse".

**Rules:**
- Always use a namespace key matching your module name (`meta_data['equipment']`,
  `meta_data['nutrition']`, etc.). Read and write only your own key.
- **Only these three records take a module's key through this guide.** Other
  Core models with a `meta_data` column of their own (`ProductTemplate`,
  `Category`, `StockLot`, `Notification`, `AuditLog`) have no namespaced write
  for modules here — use a polymorphic sidecar (Pattern 3) or a module-owned
  table for those.
- See `backend/AGENTS.md` §4 Core Neutrality ("`meta_data` namespace convention") for the full namespace convention.

---

> **Who may use Patterns 5 to 8:** all four register into the warehouse module
> through `app.modules.warehouse.warehouse_api`. A module this repository ships
> imports it like any other sibling API. A module installed from outside may
> import it too, once its `manifest.json` lists `"requires": ["warehouse"]`:
> the install-time safety scan opens `app.modules.<m>.<m>_api` of a shipped
> module to a module that declares the dependency, and nothing else of that
> module (MODULES_GUIDE.md, "The install-time safety scan"). The guide's
> worked example (`docs/MODULE_ADVANCED_GUIDE.md`, "Extending the warehouse")
> is such a module, installed the community way in the test suite.

## Pattern 5: Work-item provider (add tasks to To do and the work board)

**When:** Your module has work the floor should see beside receipts and
dispatches — a delivery to check, a certificate to file, a count that has
fallen due.

**How:** Register a provider with the warehouse module at your module's import
time (the same place the approvals target-summary providers are registered):

```python
# my_module/module.py
from app.modules.warehouse.warehouse_api import warehouse_api

from .my_module_api import my_module_api

warehouse_api.register_work_item_provider(
    'my_module', my_module_api.list_work_items_async
)
```

The provider takes `(db, org_id, query)` — `query.date_to` is the reader's
today, `query.limit` the page size and `query.done_since` (when set) the
moment from which finished work is wanted — and returns `(tasks, total)`, tasks being
`WorkItemDTO`s from `app.core.contracts`: a `kind`, the `source_kind` and
`source_id` of the record it is derived from (they key the task's assignee),
`state` (`todo`, `in_progress` or `done`), the `due_date`, and either the structured
fields a built-in sentence is made of or your own `sentence` with the
`action_label` and `action_href` (an in-app path) of the one next action.

**Rules:**
- The state is read from your records on every request, so it follows their own
  events; a cancelled source is simply no longer returned, and a finished one is
  returned as `done` only when `query.done_since` is set and it was finished at
  or after it. Nobody sets a status by hand.
- The provider is called only while your module is enabled for the
  organization (an organization with no module list has every default module
  enabled): switch it off and its tasks disappear. An error in it is logged
  and skipped; the rest of the list still arrives.
- The assignee of a task is stored by the warehouse module, not by yours.

---

## Pattern 6: Pre-post check (stop a posting with your own rule)

**When:** A rule only your customer has must hold before goods are booked —
no lot received without its certificate, no dispatch without a carrier's
reference.

**How:** Register a check with the warehouse module at your module's import
time, next to any work-item provider:

```python
# my_module/module.py
from app.core.contracts import DocumentToPostDTO
from app.core.module_sdk import InterceptorError, get_module_error_message
from app.modules.warehouse.warehouse_api import warehouse_api

from .my_module_api import my_module_api


async def require_certificates(db, org_id, document: DocumentToPostDTO) -> None:
    if document.stage != 'post' or document.type != 'IN':
        return
    for line in document.lines:
        if line.batch_number and not await my_module_api.has_certificate_async(
            db, org_id, line.batch_number
        ):
            raise InterceptorError(
                get_module_error_message(
                    'my_module', 'certificate_missing', lot=line.batch_number
                ),
                error_code='CERTIFICATE_MISSING',
            )


warehouse_api.register_pre_post_check('my_module', require_certificates)
```

with `"certificate_missing": "Missing certificate for lot {lot}"` (and its
translations) at the top level of `my_module/i18n/<lang>.json`.

The check takes `(db, org_id, document)` — a `DocumentToPostDTO` from
`app.core.contracts` with its `lines` — and is asked twice, in the posting's
own transaction: with `stage='confirm'` once a draft has drawn its number
(`document.number`) and before its stock is reserved, and with `stage='post'` before its stock moves, when each
line's `done_quantity` says what is being posted. Every door goes through
both: the one-step post ("Receive into stock", "Issue", "Transfer"), confirm,
complete, and an approval that completes a document.

**What `document.type` can be.** The code the warehouse stores on the
document, one of these (the older spellings PZ, WZ, MM, PW and RW are folded
into them when a document is created, so compare against these codes only):

| `type` | Goods | Takes goods off a shelf |
|---|---|---|
| `IN` | received from a partner | no |
| `INTERNAL_IN` | received without a partner (production output, found stock) | no |
| `OUT` | issued to a partner | yes — from `source_location_id` |
| `INTERNAL_OUT` | issued without a partner (consumption) | yes — from `source_location_id` |
| `INT` | moved from one location to another | yes — from the source; the same goods arrive at the target |
| `SCRAP` | written off | yes — from the shelf each line's stock record stands on |
| `CORRECTION` | a signed difference against an earlier document | depends on the document it corrects, which the check is not given: a negative line takes goods off a corrected receipt and puts them back for a corrected dispatch |

A stock-take result (`ADJUSTMENT`) is written already posted and never reaches
a check. To refuse goods leaving a shelf, refuse `OUT`, `INTERNAL_OUT`, `INT`
and `SCRAP`; let a `CORRECTION` through unless your rule can do without the
direction.

Each entry in `document.lines` is a `DocumentLineToPostDTO`:

| Field | Meaning |
|---|---|
| `product_template_id`, `item_id`, `name` | the product (and, when it names one, the stock record) the line is about |
| `expected_quantity`, `done_quantity`, `uom_id` | what the document planned, and what is being posted (filled in at `post`) |
| `batch_number`, `serial_number`, `expiry_date` | the lot, serial and expiry the line carries |
| `source_location_id`, `target_location_id` | where the line takes goods from and puts them (the document's own locations are on `document`) |
| `meta_data` | the fields modules keep on the line, each under its module's name |

**Rules:**
- Return to let the posting go on. Raise `InterceptorError` to refuse: the
  reader gets a 422 whose `detail.message` is your message and `detail.code`
  your `error_code`, and the transaction is rolled back — no number drawn, no
  reservation, no stock moved. A required field is a refusal that names it.
- Any other exception refuses the posting as well, as an error: a check that
  cannot answer has not said yes.
- The check is asked only while your module is enabled for the organization.
- Read, do not write, and never commit: the transaction is the posting's.
  Something to record when the posting succeeds belongs in a
  `document.completed` subscriber (Pattern 2).

**Holding a document until somebody decides.** A check can answer `'hold'`
at `stage='confirm'` instead of returning or refusing. The confirmation goes
through — the document is numbered and its stock reserved — and the document
waits in `PENDING_APPROVAL` with your module's name in `held_by`. Nothing
completes it, and no scanning session starts on it, until your module calls
one of `warehouse_api.release_document_async` (it goes on as confirmed, and
is posted when the one-step action submitted it), `withdraw_hold_async` (back
to confirmed, nothing decided) or `return_to_draft_async` (refused, back to a
draft). A hold of a module switched off for the organization stands down.
`document.confirmed_by` names who submits the document, and
`hold_document_async` parks one that is already confirmed. Pass
`on_withdrawn=` to `register_pre_post_check` to hear when a document is
cancelled or deleted, inside that transaction, and drop what you keep about
it. The approvals module gates documents exactly this way
(`app/modules/approvals/document_gate.py`); the warehouse does not import it.

---

## Pattern 7: Pick-order strategy (walk the warehouse your own way)

**When:** A picking session should walk the warehouse by a rule the default
does not know — by zone before shelf code, by order priority, by a route your
module computes from its own tables.

**How:** Register a strategy with the warehouse module at your module's import
time, next to any work-item provider and pre-post check:

```python
# my_module/module.py
from app.core.contracts import PickOrderLineDTO
from app.modules.warehouse.warehouse_api import warehouse_api


async def walk_by_certificate(db, org_id, lines: list[PickOrderLineDTO]):
    ...  # return those same lines, in the order the picker walks to them


warehouse_api.register_pick_order_strategy(
    'my_module', 'certified_first', walk_by_certificate
)
```

The strategy takes `(db, org_id, lines)` and returns those **same lines in
pick order**. Each line is a `PickOrderLineDTO` from `app.core.contracts`: the
`id` the order is written against, the line's `product_template_id` and
`product_name`, its `quantity`, the `location_id` it is taken from with
`location_path` beside it (the walk-in: the zone before the shelf, each step
its `sequence`, `short_code` and `name`), and `bin_location`, the shelf as the
floor reads it.

The organization chooses the strategy in the warehouse settings, where every
entry is offered under `<module>:pickOrderStrategies.<name>` from your module's
translation catalogue (frontend `modules/<module>/i18n/<lang>.json`) — add
that key so the choice is named in the reader's language.

**Rules:**
- The default walk (``location_sequence`` — the numbers on the locations) is
  registered the same way and is what runs when nothing is chosen, when the
  chosen name answers no strategy, or when your module is switched off for the
  organization: a disabled module costs the organization its walk, never a
  session that will not start.
- The strategy is asked once per session start, inside the start's
  transaction: read what you need, never commit, and keep it quick — every
  line of the session waits on it.
- Returning the lines in any order is the whole contract; a line left out or a
  copy returned instead of the given line is a bug in the strategy.

---

## Pattern 8: Putaway criterion (keep goods off the wrong shelves)

**When:** Your module knows that some shelves are wrong for some goods — a
chilled product needs a cold shelf, an oxidiser may not stand beside a
flammable — and the operator's putaway rules, which rank shelves by the
product and by capacity, do not.

**How:** Register a criterion with the warehouse module at your module's
import time, next to any pre-post check:

```python
# my_module/module.py
from app.core.contracts import PutawayCandidateDTO
from app.modules.warehouse.warehouse_api import warehouse_api


async def cold_shelves_only(db, org_id, candidate: PutawayCandidateDTO):
    if not await needs_cold(db, org_id, candidate.product_template_id):
        return set()
    cold = await cold_shelves(db, org_id)
    return {loc for loc in candidate.location_ids if loc not in cold}


warehouse_api.register_putaway_criterion('my_module', cold_shelves_only)
```

The criterion is asked whenever an operator's putaway rule takes a receipt
line. It takes `(db, org_id, candidate)`: a `PutawayCandidateDTO` from
`app.core.contracts` with the line's `product_template_id`, `category_id` and
`quantity` (in the product's stock unit), and `location_ids`, the rule's
shelves in the order the ranking walks them. It answers **the shelves that may
not take the line**; an empty collection lets every one through. The ranking
walks the rest and settles on the first one the goods fit, as it does without
you.

**Rules:**
- A refused shelf is not full, it is wrong for the goods, so it is never the
  over-capacity fallback either. When you refuse every shelf, the rule steps
  aside the way a rule with archived shelves does: the line goes to the
  document's destination, and the plan says so with
  `planned_rule_warning: "refused"`.
- The same answer serves the plan a reader sees before booking and the booking
  itself, so the criterion is asked in both — inside their transaction. Read
  what you need, never write or commit, and keep it quick: it is asked once
  per planned line.
- It governs the rule's own list only. A shelf the worker names on the line,
  a serial number's own record and the document's destination are a person's
  answers, not the rule's; a module that must stop those refuses the posting
  with a pre-post check (Pattern 6).
- It is asked only while your module is enabled for the organization. An
  exception it raises fails the read or the posting that asked: a criterion
  that could not answer has not said the shelf is fine.

---

## Decision Matrix

| Need | Pattern | Example |
|------|---------|---------|
| Read/write Items, Locations, Stock, Partners | **CoreAPI** | `core_api.items.get_async(...)` |
| React to "item was used up" (side effect) | **EventBus** | `context.subscribe(SystemEvent.ITEM_USED, handler)` in `on_startup` |
| Validate/block an operation before commit | **Interceptor** | Register in `InterceptorPipeline` |
| Attach approval state to any record | **Sidecar** (polymorphic) | `await approvals_api.request_approval(...)` |
| Add custom fields to an Item | **meta_data JSONB** | `meta_data['equipment']['serial']` |
| Add a field to a document or its lines | **meta_data JSONB** + form slot + pre-post check | `line.meta_data['lot_certificates']['number']` |
| Add tasks to To do and the work board | **Work-item provider** | `warehouse_api.register_work_item_provider(...)` |
| Refuse a document's posting with your own rule | **Pre-post check** | `warehouse_api.register_pre_post_check(...)` |
| Walk the warehouse in your own order while picking | **Pick-order strategy** | `warehouse_api.register_pick_order_strategy(...)` |
| Keep goods off shelves that are wrong for them when they are put away | **Putaway criterion** | `warehouse_api.register_putaway_criterion(...)` |
| Add a column to another module's table | **Not supported** — use Sidecar or meta_data | — |

---

## What NOT to do

| ❌ Anti-pattern | ✅ Correct |
|---|---|
| `from app.modules.equipment.models import EquipmentAssignment` | Use CoreAPI or a cross-module API (`*_api.py`) |
| `item.meta_data['serial'] = 'SN-123'` (flat key) | `meta_data['equipment']['serial'] = 'SN-123'` |
| Mutating data in an EventBus handler | Use an Interceptor (sync, pre-commit) |
| Adding a ForeignKey to another module's table | Use polymorphic sidecar (`target_type` + `target_id`, no FK) |
| Importing `app.models` in `router.py` | Use `core_api` facade only |

---

## Cross-Module API Contracts

When a module exposes functionality for other modules (like `approvals_api`),
it follows these rules (see `backend/AGENTS.md` §Cross-Module API Contracts):

1. **One public API per module** — all cross-module access through a single
   `*_api.py` file.
2. **Import only the public API** — never models, services, or helpers.
3. **Backward-compatible changes only** — additive (new optional params), not
   breaking.
4. **Graceful degradation** — if the module is disabled, its API methods are
   safe to call (no-op).

---

## References

- `docs/subsystems/CORE_API.md` — full CoreAPI method reference (over 30 namespaces)
- `docs/adr/ADR-007-interceptors-and-eventbus.md` — why two extension mechanisms
- `docs/adr/ADR-008-app-layer-isolation-not-rls.md` — isolation guardrail layers
- `app/modules/approvals/approvals_api.py` — reference sidecar implementation
- `app/core/_event_types.py` — EventBus event catalog (28 system events;
  re-exported as `app.core.events`)
- `app/core/interceptors.py` — InterceptorPipeline registration
- `backend/AGENTS.md` — Cross-Module API Contracts, Core Neutrality rules
