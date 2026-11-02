# Event Catalog

Auto-generated from `app.core.contracts.events.EVENT_PAYLOAD_TYPES` — do not edit by hand.

Regenerate: `docker compose exec -T backend python scripts/generate_event_catalog.py > docs/subsystems/EVENTS.md`

## Conventions

- Event names are namespaced: `<module>.<event>` (core events live in `SystemEvent`, module events in the module's own `events.py`).
- Tenant events carry `organization_id` (str) in the payload.
- Emit via `core_api.events.emit_async` / `emit_transactional_async`; subscribe via `core_api.events.subscribe` (optional `org_filter`).
- Modules declare payload contracts via `core_api.events.register_payload(name, Model)` in `on_startup`; module-owned classes live in core until the planned move (see `_payloads.py` docstrings).
- Payloads are validated against the registered contract at emit time, in `event_bus.emit` itself — raw emits included (`EventValidationError`); unregistered names fail open with a warning.
- Handlers run at least once. A handler that raises (or outlasts its 30 s bound) on a stream delivery is recorded in `event_deliveries` and retried alone — its sibling handlers are not re-run — up to 5 attempts with doubling backoff from 30 s; then it is parked as `dead` and the organization's admins get a notification. **Contract:** a handler raises before its side effect, or makes the side effect safe to repeat for the same event.

## Events

| Event | Payload type | Contract fields | Tenant | Status |
|---|---|---|---|---|
| `category.created` | `CategoryCreatedPayload` | `category_id`: str | yes | core |
| `category.deleted` | `CategoryDeletedPayload` | `category_id`: str | yes | core |
| `category.updated` | `CategoryUpdatedPayload` | `category_id`: str | yes | core |
| `document.cancelled` | `DocumentCancelledPayload` | `document_id`: str, `document_type`: str, `lines?`: list[dict[str, Any]] | yes | module |
| `document.completed` | `DocumentCompletedPayload` | `document_id`: str, `document_type`: str, `lines?`: list[dict[str, Any]] | yes | module |
| `document.confirmed` | `DocumentConfirmedPayload` | `document_id`: str, `document_type`: str, `lines?`: list[dict[str, Any]] | yes | module |
| `document.shipped` | `DocumentShippedPayload` | `document_id`: str, `document_number`: str, `document_type`: str, `carrier`: str, `tracking_number?`: str \| None, `tracking_url?`: str \| None, `package_count?`: int, `shipped_at`: str, `lines?`: list[dict[str, Any]] | yes | module |
| `equipment.checkin` | `EquipmentCheckinPayload` | `assignment_id`: str, `item_id`: str, `item_name?`: str, `assigned_to_name?`: str, `checkin_condition?`: str \| None, `new_status?`: str \| None, `user_id?`: str \| None | yes | module |
| `equipment.checkout` | `EquipmentCheckoutPayload` | `assignment_id`: str, `item_id`: str, `item_name?`: str, `assigned_to_name?`: str, `user_id?`: str \| None | yes | module |
| `item.created` | `ItemCreatedPayload` | `item?`: Any, `user_id?`: str \| None | yes | core |
| `item.deactivated` | `TenantEventPayload` | — | yes | core |
| `item.deleted` | `ItemDeletedPayload` | `item_id`: str, `user_id?`: str \| None | yes | core |
| `item.disposed` | `ItemQuantityEventPayload` | `item?`: Any, `quantity`: float, `user_id`: str | yes | core |
| `item.moved` | `ItemMovedPayload` | `item?`: Any, `changes?`: dict[str, Any], `user_id?`: str \| None | yes | core |
| `item.status_changed` | `TenantEventPayload` | — | yes | core |
| `item.transferred` | `TenantEventPayload` | — | yes | core |
| `item.updated` | `ItemUpdatedPayload` | `item?`: Any, `changes?`: dict[str, Any], `user_id?`: str \| None | yes | core |
| `item.used` | `ItemQuantityEventPayload` | `item?`: Any, `quantity`: float, `user_id`: str | yes | core |
| `label.assigned` | `TenantEventPayload` | — | yes | core |
| `label.batch_exported` | `LabelBatchExportedPayload` | `count`: int, `label_ids?`: list[str], `width_mm?`: float \| None, `height_mm?`: float \| None | yes | core |
| `label.batch_generated` | `LabelBatchGeneratedPayload` | `count`: int, `label_ids?`: list[str], `label_type?`: str \| None, `prefix?`: str \| None, `created_by?`: str \| None | yes | core |
| `label.scanned` | `TenantEventPayload` | — | yes | core |
| `location.created` | `StorageCreatedPayload` | `location_id`: str | yes | core |
| `location.deleted` | `StorageDeletedPayload` | `location_id`: str | yes | core |
| `location.updated` | `StorageUpdatedPayload` | `location_id`: str, `changes?`: dict[str, Any] | yes | core |
| `module.disabled` | `ModuleDisabledPayload` | `module_name`: str | yes | core |
| `module.enabled` | `ModuleEnabledPayload` | `module_name`: str | yes | core |
| `organization.created` | `TenantEventPayload` | — | yes | core |
| `organization.updated` | `TenantEventPayload` | — | yes | core |
| `partner.activated` | `PartnerActivatedPayload` | `partner_id`: str | yes | core |
| `partner.deactivated` | `PartnerDeactivatedPayload` | `partner_id`: str | yes | core |
| `purchase_order.cancelled` | `PurchaseOrderCancelledPayload` | `po_id`: str, `po_number`: str | yes | module |
| `purchase_order.completed` | `PurchaseOrderCompletedPayload` | `po_id`: str, `po_number`: str | yes | module |
| `purchase_order.confirmed` | `PurchaseOrderConfirmedPayload` | `po_id`: str, `po_number`: str | yes | module |
| `receipt.created_from_po` | `ReceiptCreatedFromPOPayload` | `receipt_id`: str, `receipt_number`: str, `po_id`: str, `po_number`: str | yes | module |
| `recipe.created` | `RecipeCreatedPayload` | `recipe_id`: str, `name`: str | yes | module |
| `recipe.meal_plan_generated` | `RecipeMealPlanGeneratedPayload` | `plan_id`: str, `shopping_list_id`: str, `to_buy_count`: int | yes | module |
| `recipe.picking_completed` | `RecipePickingCompletedPayload` | `session_id`: str, `recipe_id`: str, `servings`: int, `items_consumed?`: list[dict[str, Any]] | yes | module |
| `user.joined_organization` | `UserJoinedOrgPayload` | `user?`: Any | yes | core |
| `user.left_organization` | `UserLeftOrgPayload` | `user?`: Any | yes | core |
| `user.registered` | `TenantEventPayload` | — | yes | core |

## Deprecations

Deprecated events keep working until their removal release; the bus logs a warning on emit.

| Event | Replacement | Removal release |
|---|---|---|

