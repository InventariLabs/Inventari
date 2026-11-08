# Approvals Subsystem

How to integrate a module with the `approvals` module — the engine that manages
approver chains and the approval state machine for any module's operations.
For the underlying architecture see [CROSS_MODULE_EXTENSION.md](CROSS_MODULE_EXTENSION.md)
(Pattern 3: Polymorphic Sidecar).

## Integration Guide

1. **Register your target type.** Add your type to `TargetType` enum in `backend/app/modules/approvals/target_types.py`:
   ```python
   class TargetType(StrEnum):
       DOCUMENT = "document"
       PURCHASE_ORDER = "purchase_order"
       EQUIPMENT_CHECKOUT = "equipment_checkout"
       YOUR_MODULE = "your_module"  # ← add here
   ```
   The workflow editor offers only the types listed in `AVAILABLE_TARGET_TYPES`
   (`frontend/src/modules/approvals/targetTypes.ts`); add the type there too.

2. **Configure workflow per organization.** In module `on_enable`, seed default workflow.
   It is saved **switched off** (`is_active` defaults to `False`): a workflow comes into force
   only when an administrator switches it on, after the workflow screen has told them what it
   will hold (see "A workflow comes into force when switched on" below).
   ```python
   from app.modules.approvals.approvals_api import approvals_api

   await approvals_api.create_workflow(context.db, org_id, "your_module", name="Two-step approval", stages=[
       {"order": 1, "label": "Manager Approval",
        "approver_user_ids": [manager_user_id]},
       {"order": 2, "label": "Director Confirmation",
        "approver_user_ids": [director_user_id]},
   ])
   ```

3. **Guard critical operations.** In module services:
   ```python
   async def complete_my_operation(db, org_id, target_id, ...):
       await approvals_api.check_and_block(db, org_id, "your_module", target_id)
       # proceed
   ```

4. **Expose delegation endpoints.** In module router (thin proxy). The two calls
   take different identifiers: `request_approval` names *your* resource
   (`target_id`) and returns an `ApprovalRequestDTO`; `approve_stage` takes
   that request's own `id`, not the resource's:
   ```python
   @router.post('/{resource_id}/request-approval')
   async def request_approval(resource_id, current_user, db):
       request = await approvals_api.request_approval(
           db, org_id, "your_module", resource_id, current_user.id
       )
       return {'approval_request_id': request.id}

   @router.post('/approval-requests/{request_id}/approve')
   async def approve(request_id, current_user, db):
       return await approvals_api.approve_stage(db, org_id, request_id, current_user.id)
   ```
   `approvals_api` is reachable from modules in this repository; a module
   installed from outside may import only the public SDK paths.

5. **Say what a workflow for your target type would hold.** Register a scope provider at
   import time, beside the summary provider (`approvals_api.register_target_summary_provider`,
   which describes your target in the approvals queue) — `(db, org_id) -> WorkflowScope`, answered from
   your own settings by the same rule your gate applies:
   ```python
   approvals_api.register_target_scope_provider("your_module", describe_my_scope)
   ```
   `holds` is `all` (the workflow itself is the rule), `some` (with `conditions`: document
   types, a value threshold, a foreign currency) or `nothing` (your settings ask for nothing
   yet); `required_by_settings` names the settings that demand an approval on their own.
   Without a provider the workflow screen says nothing about scope.

6. **Your module decides WHEN, approvals decides HOW.**
   - Module: business logic to determine if approval is needed (threshold, conditions)
   - Approvals: engine that manages approver chain and status state machine
   - An active workflow for a target type is itself a WHEN while the module's
     own settings name nothing: configuring *who* approves is the organization
     saying the target type is approved before it moves. Once those settings
     name a threshold or a condition, they are the filter and the workflow
     only carries the answer out. See "What needs approving" below.

7. **Frontend integration.** Use the `approval_status_badge` slot:
   ```tsx
   <TypedSlot name="approval_status_badge" data={{ targetType: "your_module", targetId: id }} />
   ```

8. **Graceful degradation.** If `approvals` module is disabled, `check_and_block()` is a no-op.
   Your module should work without approvals — just without the guard. A
   module that stands down must stand down *whole*, parking included: a target
   left waiting for a decision nobody can make is worse than no control.

## What needs approving

A workflow is not only *who* approves. **An active workflow for a target type
is itself the WHEN while the module's own settings name nothing** — an
organization that configured its approvers and left its settings silent has
answered the *when* as well, and used to get no gate at all out of it
(documents confirmed and executed with no request anywhere while the
organization believed they were controlled). Once the settings name a
threshold or a list, they are the filter and the workflow only carries the
answer out: a threshold that stops filtering the moment a workflow exists is
a threshold that never worked.

| Target | When the target needs approval |
|---|---|
| `document` | the document profile asks (`approval_required_for_types`, `approval_threshold`) — and when the profile names neither, an active `document` workflow asks for every document |
| `equipment_checkout` | an active workflow exists; the module asks approvals to enforce it |
| `purchase_order` | the purchase-order settings ask (`approval_required` for all, threshold, foreign currency) — the workflow then has to exist to carry it out |

Each module keeps one place that answers this, and every caller asks it. For
documents it is the approvals module's own gate,
`backend/app/modules/approvals/document_gate.py`, which reads the profile's
half through `warehouse_api.document_sign_off_async` and asks the workflow
only when the profile named nothing. The warehouse does not call it: the gate
is a pre-post check the approvals module registers with the warehouse
(`CROSS_MODULE_EXTENSION.md` Pattern 6), asked by `confirm_document` and
`complete_document` alike, and the screen that names the consequence before
the button (`GET /approvals/documents/{id}/approval-requirement`, which weighs
a draft as the confirmed document it is about to become) asks the same
`document_needs_approval_async`.

Confirming a document that needs approval raises the request and the check
answers `'hold'`: the warehouse parks the document in `PENDING_APPROVAL` with
`held_by = 'approvals'`, and nothing completes it or starts a scanning session
on it until the decision listener releases it (approved), takes the hold back
(withdrawn) or returns it to a draft (rejected) through `warehouse_api`. A
profile that demands approval with **no active workflow** is a configuration
error: confirming raises `documents_approval_workflow_missing` instead of
sailing through. With the approvals module switched off, the whole control
stands down — its check is not asked, its hold does not stand, nothing parks,
nothing is refused. A document parked before the module went off is worked
as the confirmed document it was: its read carries `hold_stood_down: true`,
and a completion, the one-step press and a scanning session go through on
it. The door that starts the work takes the hold off — the document is
CONFIRMED again, with an entry in the journal — and withdraws the request it
waited on (`on_withdrawn`), so a module switched back on does not ask about
work already under way. A document nobody touches is left as it is, and
switching the module back on finds it in the queue. Cancelling or deleting
a document withdraws its open request (`on_withdrawn`) too.

## Whose submissions a workflow holds

Every workflow carries a **requester scope** (`requester_scope`): everyone, or the people and
roles it names — a role by the id `GET /roles` lists, the four built-in levels included. A
document, order or checkout submitted by somebody outside the scope **needs no approval**,
whatever the module's settings ask of everybody else's; inside the scope the table above
applies unchanged. Warehouse staff's receipts wait, the administrator's do not.

- The question comes first in every module's one rule: `approvals_api.requester_exempt(db,
  org_id, target_type, requester_id)` answers `True` when the active workflow leaves the person
  out (`False` with no active workflow, so a missing-workflow refusal stays what it was, and for
  an unknown requester).
- **Who the requester is.** For a document, whoever confirms it — the confirm path asks about
  the person pressing the button, the execution gate and the to-do list (which decides
  whether a row offers to start a scanning session) about `confirmed_by`, so a receipt the administrator confirmed is not held in the hands of somebody
  the workflow names. `GET /approvals/documents/{id}/approval-requirement` answers a draft for the person
  asking: two people looking at one draft can get two answers. For a purchase order, whoever
  confirms it; for a checkout, whoever performs it (the asset card's `approval-status` says
  `has_workflow: false` to somebody the workflow does not hold).
- A role is read when something is submitted, so a person moved out of a scoped role is free
  from their next submission. Requests already open are never asked again; changing the scope
  is allowed while they wait.
- **Choosing is compulsory.** `POST /approvals/workflows` has no default for `requester_scope`,
  and "chosen people" with nobody chosen is refused (422) rather than read as nobody. Workflows
  saved before the scope existed hold everyone — the column's default — so nothing changed for
  them.
- A requester outside the scope never parks, so the first-stage verdict
  (`approvals_api.first_stage_verdict`) has nothing to judge for them and answers `None`.
- **Asked before the click.** A target that parks on confirmation says so first:
  `GET /purchase-orders/{id}/approval-requirement` answers a draft order for the person asking, as
  the document's endpoint answers a draft document, and both dialogs name a dead end instead of
  promising the queue. Confirming still parks it. The verdict covers every stage the request would
  have to pass and names the first one nobody can decide, so a decidable first stage no longer
  hides a dead end behind it. The order's verdict is there whether or not the rules require the
  approval, because Request approval parks an order they would let through, and its dialog names
  the same dead end; an order parked with its request withdrawn is answered the same way, since
  Request approval is offered on it again. A module that parks a target of its own asks
  `approvals_api.first_stage_verdict` the same way and owes its reader the same sentence.

`GET /approvals/workflows` names the scope on every row by name (`requesters`: roles first, then
people), so the card can say whose submissions it holds without the roles listing.

## A workflow comes into force when switched on

A workflow is saved switched off — `POST /approvals/workflows` without `is_active`, and
`approvals_api.create_workflow` without it, both store `is_active: false` — and holds nothing
until somebody switches it on. The workflow screen does that through a dialog that states
what the workflow will hold, in the owning module's words (the scope provider above), with a
link to the settings that change it; the server holds to what the dialog showed — switching a
workflow on over the API takes the `scope` the list returned as `expected_scope` (422
`APPROVAL_SCOPE_REQUIRED` without it, 409 `APPROVAL_SCOPE_CHANGED` when the live scope has since
moved), for a target type that has a scope provider; every card shows the same phrase while the workflow is
on ("Holds: …") and what it would hold while it is off.

The reason is the table above: under a silent document profile an active document workflow
holds every confirmed document, and a workflow used to come into force the moment it was
saved, with nothing on the form saying so. An organization that set one up to look at the
feature found its first receipt, months later, parked behind a stage nobody could decide.
Workflows already in force stay in force — only a new one starts off, and editing a workflow
that is on leaves it on.

`GET /approvals/workflows` carries the scope on every row (`scope`, `null` for a target type
with no provider), computed once per target type.

## Stage edits preserve approval history

Changing stages on a workflow that has requests archives the old workflow and returns a
new workflow ID. Past requests keep their original workflow, stages and decisions; new
requests use the replacement. This applies both to PATCH and to POST overwriting the
workflow for an existing target type. PATCH keeps the active state unless the save
changes it; POST uses the submitted definition. Archived workflows remain frozen and
leave the settings list.

Stage edits remain refused while requests wait. A workflow that has never run, an
unchanged stage definition, or a name-only edit keeps the same workflow ID.

## Solvability: a stage nobody can decide

Who may decide a stage is one rule, and the decision door, the queue and the
workflow form all read it (`backend/app/modules/approvals/_services_solvability.py`):

- an **open stage** (`approver_user_ids` empty) is decidable by anyone holding
  `approvals:approve`;
- a **named stage** is decided by the people it names, who reach it through
  delegation with `approvals:read` alone as the floor — or with
  `approvals:approve`, which decides on any stage it is named on.

A stage is its label and its approvers. A `role` that older stages may still
carry was a free-form label and takes no part in this: it names nobody. (Role-holder counts are only ever a hint in the editor.)

Saving a workflow with a stage nobody could decide is **refused**
(`APPROVAL_STAGE_UNSOLVABLE`, HTTP 409) with a sentence naming the stage and
what is missing. The two dead ends have their own sentences:

- `approval_stage_open_unsolvable` — nobody in the organization holds
  `approvals:approve`, so an open stage waits for ever;
- `approval_stage_unsolvable` — none of the stage's named approvers can see
  approvals at all.

The administrator can still save it deliberately: `allow_undecidable_stages:
true` on `POST/PATCH /approvals/workflows`. The workflow editor presents that
as a confirmation ("save anyway") after showing the server's refusal, never
as a default, and warns while the stage is being written when the
organization holds no `approvals:approve` at all.

## "Nobody can decide" is visible, not silent

A request parked at a stage nobody can decide is not an empty queue. The
enriched request — `GET /approvals/requests`,
`GET /approvals/requests/{id}`, `GET /approvals/documents/{id}/approval` — carries the
verdict:

- `solvable: false` — nobody can decide the stage this request waits at;
- `undecidable_reason` — `no_approver_in_organization` (an open stage and no
  holder of the grant), `named_approvers_cannot_decide` (the stage's named
  people cannot see approvals) or `only_the_requester_can_decide` (an open
  stage whose only holder of the grant is the requester, who may not decide
  their own request).

Both are `null` for a request that is not waiting on anybody. The decision
panel — the documents approval queue, the approvals dashboard and the
document detail page all render it — shows a note naming the dead end and
the way out (grant the permission, or name an approver), so a request nobody
can decide cannot be mistaken for one waiting its turn.

## Self-approval

The engine refuses a decision by the person who raised the request — that
separation is the point of an approval step, and callers cannot override it.

An organization that needs the exception (the admin is the only approver, so
the workflow would otherwise deadlock) turns on the `approvals` module setting
`allow_admin_self_approve`. It is **off by default**, and even when on it
applies to the `admin` role only:

```json
{ "module:approvals": { "allow_admin_self_approve": true } }
```

`approve_stage` / `reject_request` read the setting themselves — a consuming
module never passes a flag, so no module can widen the rule for itself.
