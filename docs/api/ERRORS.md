# Error responses

Every error the API answers is JSON. This page is the contract a client
programs against: the shapes a body can take, the machine codes to branch on,
and where the per-endpoint additions are. The prose is written by hand and
changes with the code; the table of refusal codes below is generated from the
message catalogue (see [Refusal codes](#refusal-codes)). The [OpenAPI artifact](openapi.json) lists the routes and their
request/response bodies, and the list shape of a 422, but not the coded error
bodies, so this page is the reference for those.

The error shape and the refusal codes are stable from 0.11.0 — see the
[compatibility policy](../subsystems/CONTRACTS_STABILITY.md); the rest of the
REST API is experimental in 0.11. Error bodies may gain fields; a documented
`code` keeps its meaning, and a client should ignore fields it does not know.

## The envelope

An error body always has one top-level key, `detail`. Its value is one of
three shapes:

| Shape | When | Example |
|---|---|---|
| **Coded object** | Every refusal the current code raises: `AppException` and its subclasses, the global `ValueError`/`IntegrityError`/LLM handlers, rate limits, unhandled 500s | `{"detail": {"code": "ITEM_NOT_FOUND", "message": "Item not found"}}` |
| **List of field errors** | A 422 from request validation (a malformed body, query or path) | `{"detail": [{"loc": ["body", "name"], "msg": "Field required", "type": "missing"}]}` |
| **Plain sentence** | Only the framework answers with one, outside the application's own handlers: a path that matches no route (404, `Not Found`) and a method the route does not take (405, `Method Not Allowed`, with `Allow`). The sentence is English and has no code. Application code never raises one: a test refuses any `HTTPException` whose `detail` is a sentence, translated or not | `{"detail": "Not Found"}` |

A client should read the object when `detail` is an object, the list when it
is an array, and fall back to the string when it is a string — that order is
the stable contract.

The production-order refusals of the Maker module keep a lower-case `code`
and repeat it as `error`. Creating an order, completing one and recording a run
already made answer a 422 with `shortage_blocked`, `shortage_warning`,
`insufficient_stock` or `empty_bom`, and with the shortage list (`shortages`,
plus `short_at_create` for `insufficient_stock`) or the recipe (`recipe_id`,
`recipe_name`) next to it.

## The coded object

```json
{
  "detail": {
    "code": "AI_CONNECTION_TARGET_REQUIRED",
    "message": "Choose a saved connection or a provider to test.",
    "field": "connection_id",
    "lang": "en"
  }
}
```

| Field | Always | Meaning |
|---|---|---|
| `code` | yes | Stable uppercase snake_case machine code. Branch on this, not on `message`. |
| `message` | yes | The sentence a person reads, in the request language. |
| `field` | no | The one request field at fault, when the refusal names one. |
| `lang` | no | The language `message` is written in (`en`, `pl`, `de`, `fr`, `es`, `pt`), when the refusal translated its message with the request's language. A sentence produced elsewhere (a service's own text) carries no language claim, and some handlers (the 500 and LLM 503 paths) do not stamp it even though their sentence comes from the catalogue. |
| other | no | Code-specific data, described below. |

### Request language

`Accept-Language` selects the language of catalogue messages, including the
`message` of a coded refusal and a 422 entry that came from a validator. The
default is the instance's `DEFAULT_LANGUAGE` (English unless configured). `pt`
is a community language: a catalogue message it has not been given yet is
answered in English.

### Code-specific fields

Some codes carry the numbers a screen needs, so it does not have to parse the
sentence:

| Code | Extra fields |
|---|---|
| `AI_USAGE_LIMIT_EXCEEDED` | `limit_key`, `used`, `limit`, `period_start`, `period_end` (a 429; the organization spent its AI budget). The code is the same for both ceilings; `limit_key` says which. The `AI_USAGE_LIMIT_EXCEEDED_REQUESTS` and `_SCANS` rows of the table below are the keys of the two sentences behind it, not separate codes on this response |
| `PERIOD_CLOSED` | none today; the sentence names the period |
| `STOCK_STATE_IMPOSSIBLE` | none today; the message says which stock guard refused the write |
| `RATE_LIMIT_EXCEEDED` | `limit` — the ceiling that was hit, e.g. `10 per 1 minute` (see below) |
| `LLM_PROVIDER_*` | none today; the message names the connection and model when both are known. A 503, except from the connection test (`POST /ai-connections/test`), which answers the same code as a 400 |

The list is not exhaustive: other refusals attach the rows they are about, for
example the stock take completion refusals (`moved_items`,
`awaiting_recount_items`, `unexplained_items`, `over_tolerance_items`,
`over_cap_items`), `ROLE_IN_USE` (`member_count`), `BULK_SCOPE_TOO_LARGE`
(`matched`, `limit`) and `SESSION_HELD_BY_OTHER_USER` (`held_session_id`,
`held_by`). Read the router of the code you integrate.

## Status codes and codes

The status says what class of thing went wrong; the code says which one.

| Status | Codes a client commonly branches on |
|---|---|
| 400 | The refusal's own code — `STORAGE_NOT_FOUND`, `ITEM_ALREADY_DELETED`, … (see [Refusal codes](#refusal-codes)). `VALIDATION_ERROR` only where a refusal names no catalogue key. `TEXT_HAS_A_NULL_CHARACTER` for text that holds U+0000 (`%00` in an address), in any field of any request: the database stores no such character |
| 401 | `INVALID_CREDENTIALS` (login), `TOKEN_REVOKED` and `TOKEN_ABSOLUTE_EXPIRY` (token refresh), `TOKEN_INVALID`, `INVALID_API_KEY`, `API_KEY_OWNER_INACTIVE`, and `NOT_AUTHENTICATED` — a request that carries no credential at all to an authenticated route, and a media file under `/uploads` asked for with neither a bearer token nor the sign-in cookie. The last four carry `WWW-Authenticate: Bearer`; the first three do not |
| 403 | `FORBIDDEN` (permission or missing organization), `API_KEY_SCOPE_REFUSED`, `MODULES_NOT_ENABLED` (the module is switched off for the organization), `USER_BLOCKED`, `API_KEY_CANNOT_CREATE` and its siblings |
| 404 | `NOT_FOUND`, and one code per resource: `ITEM_NOT_FOUND`, `STORAGE_NOT_FOUND`, `STOCK_TAKE_NOT_FOUND`, `STOCK_LOT_NOT_FOUND`, `RECIPE_NOT_FOUND`, `MEAL_PLAN_NOT_FOUND`, `USER_NOT_FOUND`, `AI_CONNECTION_NOT_FOUND`, … |
| 409 | `PERIOD_CLOSED`, `STOCK_STATE_IMPOSSIBLE`, and the conflict's own code: `APPROVAL_REQUIRED`, `RECIPE_IN_USE`, `ROLE_IN_USE`, `PARTNER_CONFLICT`, `SHOPPING_LIST_NOT_EDITABLE`, `RECIPE_NAME_TAKEN`, `AI_CONNECTION_NAME_TAKEN`, `CONNECTION_STILL_BOUND`, … |
| 413 | `FILE_TOO_LARGE`, `DEMO_UPLOAD_FILE_LIMIT`, `DEMO_UPLOAD_TOTAL_LIMIT` |
| 422 | the list shape above; a router that refuses one field after validation answers a coded object with a `field` (`VALIDATION_ERROR`, or the refusal's own code such as `WEBHOOK_URL_SCHEME`); an interceptor's veto answers its own code (`INTERCEPTOR_ERROR` on an item update); also `APPROVAL_SCOPE_REQUIRED`, `BULK_SCOPE_TOO_LARGE` and the production shapes described under the envelope |
| 415 | `FILE_TYPE_NOT_ALLOWED` (attachments) |
| 429 | `RATE_LIMIT_EXCEEDED`, `AI_USAGE_LIMIT_EXCEEDED`, `DEMO_SANDBOX_CAP_REACHED`, `TOO_MANY_STREAMS` |
| 500 | `INTERNAL_ERROR` — never carries an exception's own text; the log has it, under the `X-Request-ID` the response carries like every other. A PDF that could not be rendered answers `PDF_GENERATION_FAILED` |
| 502 | `EMAIL_SEND_FAILED` (the email test), `EMAIL_DELIVERY_FAILED` (a purchase order's email) |
| 503 | `LLM_PROVIDER_UNREACHABLE`, `LLM_PROVIDER_TIMEOUT`, `LLM_PROVIDER_KEY_REJECTED`, `LLM_PROVIDER_LIMIT`, `LLM_PROVIDER_MODEL_UNKNOWN`, `LLM_PURPOSE_UNBOUND`, `LABEL_RENDERER_UNAVAILABLE`, `VISION_AI_NOT_CONFIGURED`, `DATABASE_NOT_INITIALISED`, `DEMO_SANDBOX_POOL_EMPTY` |

A resource code is `RESOURCE.upper() + '_NOT_FOUND'`; a conflict code is chosen
by the domain and matches the `ConflictException(code, message)` call in the
router. A 409 that wraps a service's refusal (a taken partner code, an approval
the engine would not take, a label code already in use) answers the refusal's
own code from [Refusal codes](#refusal-codes) — `APPROVAL_WORKFLOW_NEEDS_STAGE`,
not one `APPROVAL_ERROR` for every approval refusal. The family code
(`PARTNER_CONFLICT`, `APPROVAL_ERROR`, `LEAVE_ORG_FAILED`, `LABEL_CODE_CONFLICT`,
`STUB_CREATION_FAILED`, `WEBHOOK_URL_INVALID` — the last one on a 422 with
`field: "url"`) is only what is left when the service raised a sentence
without a key. Grep the backend for the endpoint you are integrating if a code is
missing from this table — the table names the families, not every member.

## Per-row refusals in a batch

A batch endpoint — a bulk edit, retire, archive, return or purge of assets, an
asset import, an import of order lines — answers 200 when the batch ran, and
lists the rows it refused under `errors`. Each entry says which row (`item_id`,
`row` or `index`, as the endpoint numbers them), the sentence in `error`, and
the refusal's `code` from the table below:

```json
{
  "updated": 1,
  "errors": [
    {"item_id": "…", "error": "The asset is still checked out to someone. Check it in first.", "code": "EQUIPMENT_STILL_ASSIGNED"}
  ]
}
```

`code` is absent or `null` only for a sentence raised without a catalogue key. Branch on
it, as on the envelope's.

The two imports (assets and order lines) list at most the first 20 refused
rows in `errors`; the full count is `failed` for assets and `total_errors` for
order lines.

## Refusal codes

A refusal of a business rule answers 400 — or the status its route gives it, a
403, a 404, a 409 or a 422 — and carries the reason in `code`:
the key of the sentence in the message catalogue, upper-cased
(`item_already_deleted` → `ITEM_ALREADY_DELETED`). `message` is that sentence in the
request language, so the same refusal reads differently in Polish and German
and carries the same `code`. Branch on `code`; a code does not change meaning
or spelling, and the wording of `message` may.

`VALIDATION_ERROR` is what is left when a refusal names no catalogue key: a
router that refuses a field with a `field` after validation, and an internal
error that surfaced as a 400. A 422 entry of the list shape carries the same
`code` next to `msg` when a validator refused with a catalogue key.

A few refusals carry a code of their own that is not a catalogue key, with the
data the screen needs next to it (for example `RECEIPT_EXPIRY_REQUIRED`,
`RECORD_UNIT_MISMATCH`, `CORRECTION_ITEM_MISSING` and `SURPLUS_NEEDS_CONFIRMATION`);
they are not in the table.

The table is generated from the catalogue by
`backend/scripts/generate_error_codes.py` and checked by the test suite, so it
cannot drift from the catalogue. A refusal that chooses its key at run time
is listed with every key it can choose. The message shown is the English one;
`{name}` marks a value filled in at request time.

Two families keep the lowercase codes they answered before the catalogue
existed, and the table lists them as they appear on the wire: the focus-mode
refusals and the profile-switch refusals (`unknown_module`, `already_in_focus`,
`not_in_focus`, `focus_module_always_on`, `focus_module_not_allowed`,
`module_not_allowed`, `dependency_cycle`, `dependency_closure`). They answer
`409` with `code`, `message`, `lang` and the context the message is built
from: `module` (the module refused, or the one whose requirement failed),
`unknown_modules`, `not_allowed_modules` or `modules` (a list, which the
message joins with commas), and `missing_dependency`. They are sorted after
the upper-case codes. Two refusals can share
a lowercase code (`unknown_module` is both a focus target and a profile entry
that is not registered; `dependency_cycle` likewise); the message tells them
apart.

<!-- BEGIN GENERATED REFUSAL CODES (scripts/generate_error_codes.py) -->
| Code | English message |
|---|---|
| `AI_CONNECTION_TARGET_REQUIRED` | Choose a saved connection or a provider to test. |
| `AI_PROVIDER_INVALID` | Invalid provider. Allowed: {allowed} |
| `AI_PURPOSE_UNKNOWN` | Unknown AI purpose '{purpose}' |
| `AI_USAGE_LIMIT_EXCEEDED_REQUESTS` | The organization has used {used} of {limit} AI requests allowed for {period}. Contact your administrator to raise the limit. |
| `AI_USAGE_LIMIT_EXCEEDED_SCANS` | The organization has used {used} of {limit} label scans allowed for {period}. Contact your administrator to raise the limit. |
| `ANNOUNCEMENT_TYPE_INVALID` | Invalid announcement type. Allowed: {allowed} |
| `API_KEYS_LIMIT_REACHED` | The organization already has {count} active API keys, which is the maximum. Revoke one to create another. |
| `API_KEY_CANNOT_CREATE` | API keys cannot create other API keys |
| `API_KEY_CANNOT_MANAGE` | API keys cannot manage other API keys |
| `API_KEY_CANNOT_REVOKE` | API keys cannot revoke other API keys |
| `API_KEY_PERMISSION_NOT_GRANTABLE` | An API key cannot be given {permission}: you do not hold it, or no key carries it |
| `API_KEY_PERMISSION_OUTSIDE_SCOPE` | The permission {permission} is not part of the scopes chosen for this key |
| `API_KEY_SCOPE_UNKNOWN` | There is no API key scope called "{scope}" |
| `APPROVAL_APPROVE_INVALID_STATUS` | Only a request awaiting a decision can be approved. |
| `APPROVAL_CANCEL_INVALID_STATUS` | Only an open request can be withdrawn. |
| `APPROVAL_CANNOT_APPROVE_OWN_REQUEST` | You cannot approve your own request. |
| `APPROVAL_CANNOT_REJECT_OWN_REQUEST` | You cannot reject your own request. |
| `APPROVAL_DECISION_ALREADY_TAKEN` | Someone else has already decided on this request. |
| `APPROVAL_GRANTED_FOR_ANOTHER_HOLDER` | The approval was granted for a checkout to {holder}. Request one for this checkout. |
| `APPROVAL_NOT_STAGE_APPROVER` | You are not an approver for this stage. |
| `APPROVAL_NO_ACTIVE_WORKFLOW` | No active approval workflow is configured for this action. |
| `APPROVAL_ONLY_REQUESTER_CAN_CANCEL` | Only the person who raised the request can withdraw it. |
| `APPROVAL_REJECT_INVALID_STATUS` | Only a request awaiting a decision can be rejected. |
| `APPROVAL_REQUESTER_SCOPE_EVERYONE_WITH_NAMES` | A workflow that holds everyone names no people or roles. |
| `APPROVAL_REQUESTER_SCOPE_NAMES_NOBODY` | Choose at least one person or role, or everyone. |
| `APPROVAL_REQUEST_ALREADY_OPEN` | An approval request is already open for this record. |
| `APPROVAL_REQUEST_NOT_FOUND` | Approval request not found |
| `APPROVAL_REQUIRED_AFTER_REJECTION` | The approval for this action was rejected. Request a new one before continuing. |
| `APPROVAL_REQUIRED_FIRST` | This action needs an approval first. Request one before continuing. |
| `APPROVAL_SCOPE_CHANGED` | What this workflow would hold has changed since you opened this — read it again, and switch the workflow on if it is still what you want. |
| `APPROVAL_SCOPE_REQUIRED` | Switching a workflow on needs the scope it will hold, as shown to you — send "expected_scope", or the workflow stays off. |
| `APPROVAL_STAGE_OPEN_UNSOLVABLE` | Stage "{label}" waits for anyone holding the approvals approve permission, and nobody in this organization holds it — no request would ever be decided. Grant it to somebody, or name an approver. |
| `APPROVAL_STAGE_UNSOLVABLE` | Stage "{label}" could never be decided: none of its named approvers can see approvals. Add at least one approver who has approvals access. |
| `APPROVAL_TARGET_NOT_FOUND` | This record does not exist, so no approval can be requested for it. |
| `APPROVAL_UNKNOWN_APPROVERS` | Some of the selected approvers do not belong to this organization. |
| `APPROVAL_UNKNOWN_REQUESTERS` | Some of the selected people or roles do not belong to this organization. |
| `APPROVAL_WORKFLOW_ARCHIVED` | This workflow was deleted and is archived: its requests still show the stages they went through, so it cannot be changed or switched on again. Create a new workflow in its place. |
| `APPROVAL_WORKFLOW_DELETE_BLOCKED` | This workflow cannot be deleted while requests are waiting on it ({count}: {documents}). The person who raised a request can withdraw it, and an approver can decide it — settle them first. |
| `APPROVAL_WORKFLOW_INACTIVE` | The approval workflow behind this request is no longer active. |
| `APPROVAL_WORKFLOW_MODIFY_BLOCKED` | This workflow cannot be changed while requests are waiting on it ({count}: {documents}). The person who raised a request can withdraw it, and an approver can decide it — settle them first. |
| `APPROVAL_WORKFLOW_NEEDS_STAGE` | An approval workflow needs at least one stage. |
| `APPROVAL_WORKFLOW_NOT_FOUND` | Approval workflow not found |
| `APPROVAL_WORKFLOW_NO_STAGES` | This approval workflow has no stages configured. |
| `APPROVAL_WORKFLOW_REQUIRED_BUT_MISSING` | This needs an approval, but no active approval workflow exists for it. Create one, or drop the requirement. |
| `ASSIGNMENT_ALREADY_RETURNED` | This equipment has already been confirmed as returned — no further confirmation is needed. |
| `ASSIGNMENT_NOT_FOUND` | Assignment not found |
| `ATTACHMENT_FILE_TYPE_INVALID` | Invalid file type: {file_type} |
| `ATTESTATION_ASSIGNMENT_REQUIRED` | Select the asset you are reporting a problem with |
| `ATTESTATION_COMPLETE_NOT_ALLOWED` | A campaign that is {status} cannot be completed |
| `ATTESTATION_EXPIRED` | Attestation link has expired |
| `ATTESTATION_NOT_DRAFT` | This campaign is already {status} — only a draft can be launched |
| `ATTESTATION_NOT_FOUND` | Attestation link not found |
| `ATTESTATION_NO_ACTIVE_ASSIGNMENTS` | No active assignments found for the configured scope |
| `ATTESTATION_REFUSED` | This attestation link cannot accept this action. Ask the organisation that sent it for a new link. |
| `ATTESTATION_REMINDERS_NOT_ACTIVE` | Reminders can only be sent for a campaign that is running |
| `ATTESTATION_SCOPE_EXCEEDS_LIMIT` | The scope covers more than {limit} items. Narrow it, or split the attestation into smaller ones. |
| `BARCODE_ALREADY_EXISTS` | Barcode {barcode} already exists |
| `BARCODE_IN_USE` | Barcode already in use: {barcode} |
| `BARCODE_NAMES_ONE_RECORD` | One barcode cannot name {count} records: {barcode} |
| `BARCODE_OR_ITEM_ID_REQUIRED` | barcode or item_id required |
| `BARCODE_OR_SKU_REQUIRED` | Either barcode or sku query parameter is required |
| `BOM_CYCLE_DETECTED` | BOM cycle detected at {template_id} |
| `BOM_DEPTH_EXCEEDED` | This BOM is nested more than {max_depth} levels deep — too deep to resolve. |
| `BOM_LINE_ALREADY_EXISTS` | This BOM already lists that ingredient — a BOM line between the two products already exists. |
| `BOM_LINE_CYCLE` | This line would close a cycle: the product would become an ingredient of its own BOM. |
| `BOM_LINE_NOT_FOUND` | BOM line not found |
| `BOM_LINE_PARENT_MISMATCH` | The line's parent product does not match the product this BOM produces |
| `BOM_LINE_SELF_REFERENCE` | A BOM line cannot reference the product itself — it would make the product an ingredient of its own BOM. |
| `BOM_LINE_UNIT_NOT_CONVERTIBLE` | This ingredient is kept in {stock_unit}, and {line_unit} cannot be read as {stock_unit}. Use a unit of the same kind, or record what one {stock_unit} weighs or holds on the product. |
| `CAMPAIGN_CLOSED` | This attestation campaign has been closed — your confirmation can no longer be recorded. If you still hold the equipment, please contact your organisation. |
| `CAMPAIGN_DEADLINE_PAST` | Campaign deadline must be today or later |
| `CAMPAIGN_NOT_FOUND` | Campaign not found |
| `CANNOT_CHANGE_OWN_ROLE` | Cannot change your own role |
| `CANNOT_REMOVE_YOURSELF` | Cannot remove yourself |
| `CATEGORY_DELETE_BLOCKED_BY_ITEMS` | Cannot delete category: it is in use ({count}). Move its products to another category first. |
| `CATEGORY_NAME_TAKEN` | Category with this name already exists |
| `CATEGORY_NOT_FOUND` | Category not found |
| `CATEGORY_SYSTEM_FIELD_LABEL_LOCKED` | The name of the "{field}" field belongs to the product catalog and cannot be changed. |
| `CONVERSION_NOT_FOUND` | Conversion not found |
| `CONVERSION_NOT_FOUND_OR_SYSTEM` | Conversion not found or is a system default |
| `COUNTED_QUANTITY_ABOVE_CEILING` | The counted quantity {quantity} is past what the column holds — the largest storable value is {ceiling} |
| `CURRENT_PASSWORD_INCORRECT` | Current password is incorrect |
| `CUSTOM_FIELD_REQUIRED` | The field "{field}" is required |
| `CYCLE_COUNT_NO_MATCHING_ITEMS` | No items match the schedule criteria |
| `CYCLE_COUNT_SCHEDULE_NOT_FOUND` | Cycle count schedule not found |
| `CYCLE_COUNT_SCOPE_LOCATION_REQUIRED` | storage_location_id is required in scope_filter |
| `DEMO_CREDENTIALS_LOCKED` | This is the public demo, where every email lands in a public inbox. Passwords cannot be changed or reset here, and visitors need no account. |
| `DEMO_REGISTRATION_LOCKED` | This is the public demo, where visitors need no account. Request Access is not available here — use Try the demo to look around. |
| `DEMO_SMTP_SETTINGS_LOCKED` | This is the public demo, so the mail server is fixed: every message the app would send is caught in the demo inbox. Email settings cannot be changed here. |
| `DISCREPANCY_REASON_REQUIRED` | A discrepancy reason is required |
| `DOCUMENTS_APPROVAL_WORKFLOW_MISSING` | This document needs an approval, but nobody has been set up to give it yet. Ask your administrator to set it up. |
| `DOCUMENTS_PDF_REQUIRE_CONFIRMED` | A merged PDF is produced from confirmed or completed documents only. Not printable: {numbers}. |
| `DOCUMENT_ADJUSTMENT_LINES_REFERENCE_ITEMS` | Adjustment document lines must reference existing items |
| `DOCUMENT_ADJUSTMENT_WOULD_GO_NEGATIVE` | The adjustment would take {item} below zero: current {current}, change {delta}, result {result}. |
| `DOCUMENT_CANCEL_INVALID_STATUS` | Only DRAFT, PENDING_APPROVAL or CONFIRMED documents can be cancelled |
| `DOCUMENT_COMPLETE_INVALID_STATUS` | Cannot complete a document in {status} status |
| `DOCUMENT_COMPLETE_SKIPPED_LINES` | Completing would book the skipped lines as picked or received in full, with nobody having said what became of them. Skipped lines: {lines}. Put each one back on the list, or answer it as short with a reason, before completing — complete_as_planned does not cover them |
| `DOCUMENT_COMPLETE_UNANSWERED_LINES` | Completing without an answer for every line would book the unanswered ones as delivered in full. Unanswered lines: {lines}. Send their quantities, or set complete_as_planned=true to book them as planned |
| `DOCUMENT_CONFIRM_INVALID_STATUS` | Cannot confirm a document in {status} status |
| `DOCUMENT_CORRECTION_ABOVE_EXPECTED` | A correction of {quantity} exceeds the expected quantity {expected} in absolute terms. |
| `DOCUMENT_CORRECTION_BELOW_ZERO` | A correction of {delta} would take line {line} below zero — {left} of {done} is left to correct |
| `DOCUMENT_CORRECTION_LINES_REFERENCE_ITEMS` | Correction document lines must reference existing items |
| `DOCUMENT_CORRECTION_LOCKED` | Correction documents are locked — only notes can be changed. Attempted to change: {fields}. Cancel and create a new correction if the data is wrong. |
| `DOCUMENT_CORRECTION_MISSING_ORIGINAL` | This correction does not name the document it corrects. |
| `DOCUMENT_CORRECTION_NO_LINES` | A correction needs at least one line |
| `DOCUMENT_CORRECTION_ORIGINAL_NOT_FOUND` | The corrected document {document} was not found. |
| `DOCUMENT_CORRECTION_REQUIRES_COMPLETED` | Only a completed document can be corrected |
| `DOCUMENT_CORRECTION_SIGN_MISMATCH` | A correction must keep the sign of the expected difference: {quantity} against {expected}. |
| `DOCUMENT_CORRECTION_TYPE_NOT_CORRECTABLE` | Documents of this type cannot be corrected |
| `DOCUMENT_CORRECTION_WOULD_GO_NEGATIVE` | The correction would take {item} below zero: current {current}, change {delta}, result {result}. |
| `DOCUMENT_DELETE_STATUS` | Only DRAFT documents can be deleted |
| `DOCUMENT_DELIVERY_LINES_REFERENCE_ITEMS` | Delivery document lines must reference existing items |
| `DOCUMENT_DONE_QUANTITY_ABOVE_EXPECTED` | The done quantity {quantity} exceeds the expected quantity (max {expected}). |
| `DOCUMENT_DONE_QUANTITY_NEGATIVE` | The done quantity cannot be negative: {quantity}. |
| `DOCUMENT_EXECUTION_LINE_FOREIGN` | This execution line does not belong to the document. |
| `DOCUMENT_EXECUTION_LINE_REPEATED` | Each document line can be executed only once. |
| `DOCUMENT_FIELDS_CLOSED` | A completed or cancelled document's fields can no longer change |
| `DOCUMENT_FILTER_UNKNOWN` | This filter is not available: no enabled module offers it ({name}). |
| `DOCUMENT_HELD_QUANTITY_ABOVE_RECEIVED` | The held quantity {quantity} exceeds the quantity received ({received}). |
| `DOCUMENT_HELD_QUANTITY_NEEDS_CODE` | A held quantity needs the code Damage or Quality hold. |
| `DOCUMENT_HELD_QUANTITY_NEEDS_RECEIPT` | Only a receipt can hold goods back. |
| `DOCUMENT_HELD_QUANTITY_NEGATIVE` | The held quantity cannot be negative: {quantity}. |
| `DOCUMENT_INSUFFICIENT_STOCK` | Insufficient stock to confirm: {quantity} of {needed} could not be reserved |
| `DOCUMENT_INSUFFICIENT_STOCK_RECORD_ELSEWHERE` | Insufficient stock to confirm: {quantity} of {needed} could not be reserved on "{document_shelf}"; the record "{item_name}" stands on "{record_shelf}" — point the document at that shelf, or move the record first |
| `DOCUMENT_LINES_NEED_STOCK_ROW` | A document of type {type} takes goods off a shelf, so every line has to name the stock it takes them from — lines {lines} name only a product |
| `DOCUMENT_LINES_QUANTITY_NOT_POSITIVE` | Lines {lines} have a quantity of zero or less. Correct them before confirming. |
| `DOCUMENT_LINE_NEEDS_IDENTITY` | The document line must name a record, a product or a name. |
| `DOCUMENT_NOT_FOUND` | Document not found |
| `DOCUMENT_ORIGINAL_LINE_MISSING` | Line {line} does not exist in document {number} |
| `DOCUMENT_PARTIAL_NEEDS_DISCREPANCY_CODE` | A partial execution needs a discrepancy code. |
| `DOCUMENT_PARTNER_MUST_BE_CUSTOMER_OR_SUPPLIER` | An issue takes a customer or a supplier as its partner |
| `DOCUMENT_PARTNER_MUST_BE_SUPPLIER_OR_MANUFACTURER` | A receipt takes a supplier, a manufacturer or a customer as its partner |
| `DOCUMENT_PARTNER_TAX_ID_REQUIRED` | Partner "{name}" has no tax ID, and this organization's documents require one to confirm. Add the tax ID on the partner, mark the partner as a private person (consumer), or turn off "Require partner tax ID" in Document settings. |
| `DOCUMENT_PDF_REQUIRES_CONFIRMED` | A PDF is produced from a confirmed or completed document. This one is {status}. |
| `DOCUMENT_POST_ALREADY_POSTED` | This document has already been posted — nothing was posted a second time. |
| `DOCUMENT_POST_CANCELLED` | This document was cancelled, so it cannot be posted. |
| `DOCUMENT_POST_WAITING_FOR_APPROVAL` | This document is already waiting for approval; the stock moves once it is approved. |
| `DOCUMENT_PRESET_UNKNOWN` | There is no preset named {name}. Available: {available} |
| `DOCUMENT_REASON_SCRAP_ONLY` | Only a scrap document can carry a scrapping reason |
| `DOCUMENT_RECEIPT_LINES_NEED_PRODUCT` | Lines {lines} name no product from your list, and a receipt puts only products into stock — pick each one from the list or add it as a new product |
| `DOCUMENT_RECORD_STANDS_ELSEWHERE` | The record "{item_name}" stands on "{record_shelf}", but the document takes from "{document_shelf}" — point the document at the shelf the record stands on, or move the record first |
| `DOCUMENT_RETURN_NO_LINES` | A return needs at least one line |
| `DOCUMENT_RETURN_QUANTITY_EXCEEDS_LEFT` | A return of {quantity} is more than what is left of line {line} ({left} of {done}) |
| `DOCUMENT_RETURN_QUANTITY_NOT_POSITIVE` | The quantity returned on line {line} must be greater than zero |
| `DOCUMENT_RETURN_REQUIRES_COMPLETED` | A return can only be made against a completed document |
| `DOCUMENT_RETURN_TYPE_NOT_ELIGIBLE` | Returns can only be made against receipts, issues and transfers |
| `DOCUMENT_REWORK_WRONG_STATUS` | A document in {status} status cannot be reworked to draft; only a confirmed document or one awaiting approval can. |
| `DOCUMENT_SCRAP_LINES_REFERENCE_ITEMS` | Scrap document lines must reference existing items |
| `DOCUMENT_SCRAP_REASON_REQUIRED` | A scrap document says why the goods are written off: choose a reason, and with Other write it in the notes |
| `DOCUMENT_SHIPMENT_DISPATCH_ONLY` | Only a dispatch records a shipment: a carrier takes goods that leave the warehouse. |
| `DOCUMENT_TEMPLATE_WRONG_MODULE` | A document template belongs to the warehouse module |
| `DOCUMENT_TRACKING_TEMPLATE_INVALID` | The tracking link for "{carrier}" must be a web address starting with https:// or http:// and containing {{tracking_number}} where the number goes. |
| `DOCUMENT_TRANSFER_LINES_REFERENCE_ITEMS` | Transfer document lines must reference existing items |
| `DOCUMENT_TYPE_CONFIG_NOT_FOUND` | Document type configuration not found |
| `DOCUMENT_TYPE_INVALID` | There is no document type {type} |
| `DOCUMENT_TYPE_REQUIRES_PARTNER` | This document type requires a partner. |
| `DOCUMENT_TYPE_REQUIRES_SOURCE_LOCATION` | This document type needs a source location |
| `DOCUMENT_TYPE_REQUIRES_TARGET_LOCATION` | This document type needs a target location |
| `DOCUMENT_UNDO_BLOCKED` | This cannot be undone: {reason} Use Correct to change what is left instead. |
| `DOCUMENT_UNDO_NOTHING_LEFT` | Everything this document posted has already been reversed |
| `DOCUMENT_UNDO_REQUIRES_COMPLETED` | Only a posted document can be undone |
| `DOCUMENT_UNDO_STOCK_USED` | This cannot be undone: later movements used the stock it posted. Use Correct to change what is left instead. |
| `DOCUMENT_UNDO_TYPE_NOT_SUPPORTED` | Only a receipt, an issue or a transfer can be undone |
| `DOCUMENT_UNIT_PRICE_REQUIRED` | Every line needs a unit price — missing on lines {lines} |
| `DOCUMENT_UPDATE_STATUS` | Only DRAFT documents can be updated |
| `DOCUMENT_ZONE_SPLIT_NEEDS_STOCK_UNIT` | The line for "{item_name}" is written in a unit other than the product's stock unit and cannot be split over several shelves — write it in the stock unit, or take it from one shelf |
| `EQUIPMENT_ASSIGNMENT_ALREADY_ACTIVE` | Item already has an active assignment |
| `EQUIPMENT_ASSIGNMENT_NEEDS_PERSON_OR_LOCATION` | Name the person receiving the asset or the location it is deployed to, not both |
| `EQUIPMENT_BULK_ITEM_FAILED` | This asset could not be changed. |
| `EQUIPMENT_CANNOT_CHECKOUT_IN_MAINTENANCE` | Cannot check out an asset that is in maintenance; set it to Available first |
| `EQUIPMENT_CANNOT_CHECKOUT_RETIRED` | Cannot check out a retired asset |
| `EQUIPMENT_DEPLOY_REQUIRES_CHECKOUT` | An asset becomes deployed by checking it out to someone. Check it out instead of setting the status. |
| `EQUIPMENT_STATUS_INVALID` | Invalid status: {status} |
| `EQUIPMENT_STATUS_TRANSITION_DENIED` | Cannot change status from {old} to {new} |
| `EQUIPMENT_STATUS_TRANSITION_FROM_RETIRED` | Cannot change status from {old} to {new}. Retired assets must be explicitly unretired first. |
| `EQUIPMENT_STILL_ASSIGNED` | The asset is still checked out to someone. Check it in first. |
| `EXTRA_COST_CURRENCY_MISMATCH` | The extra cost is in a different currency than the document. Enter it in the document's currency — converting at a rate nobody recorded would put a number in the stock value with no history behind it. |
| `EXTRA_COST_DOCUMENT_POSTED` | This receipt is already posted, so an extra cost cannot be added to it: the goods may have left the shelf and there is nothing left to charge. Issue a correction to the receipt while its period is open instead. |
| `EXTRA_COST_NOT_A_RECEIPT` | Extra costs belong on a receipt: only goods coming in can carry the cost of getting them here. |
| `FAILED_TO_READ_FILE` | Failed to read file: {error} |
| `FIELD_CANNOT_BE_CLEARED` | These fields cannot be cleared: {fields}. |
| `FIELD_MONEY_AMOUNT` | The amount of the field "{field}" must be a number |
| `FIELD_MONEY_CURRENCY` | The currency of the field "{field}" must be a 3-letter ISO 4217 code, such as EUR |
| `FIELD_MONEY_SHAPE` | The field "{field}" must hold an amount and a currency, and nothing else |
| `FIELD_MULTI_SELECT_SHAPE` | The field "{field}" must be a list of options |
| `FIELD_OPTIONS_REQUIRED` | A field of type {type} needs a non-empty list of options |
| `FIELD_OPTION_NOT_ALLOWED` | The value "{value}" is not one of the options of the field "{field}": {options} |
| `FIELD_REQUIRED` | This field is required |
| `FIELD_SELECT_SHAPE` | The field "{field}" must be a single option |
| `FILE_CONTENT_TYPE_MISSING` | The file does not say what type it is (the Content-Type header is missing). |
| `FILE_EMPTY` | The file is empty. |
| `FILE_NOT_WEBP` | This file is not a valid WebP image. |
| `FILE_SIGNATURE_MISMATCH` | File signature does not match the declared file type |
| `FILE_TOO_LARGE` | File exceeds the maximum allowed size (10 MB) |
| `FILE_TYPE_NOT_ALLOWED` | File type not allowed |
| `FILE_TYPE_NOT_ALLOWED_LIST` | File type not allowed. Allowed: {allowed} |
| `FORBIDDEN` | Access denied |
| `HEX_COLOR_INVALID` | Invalid hex color: {color}. Use format #RGB or #RRGGBB |
| `HOME_SHELF_NOT_STOCK` | This location does not take stock, so it cannot be a home location. |
| `HOME_SHELF_QUARANTINE` | A quarantine location cannot be a home location: goods held back are not kept there. |
| `HOME_SHELF_RECEIVING` | A receiving area cannot be a home location: goods only wait there. |
| `IMAGE_UNREADABLE` | This file could not be read as an image |
| `IMPORT_ASSET_NAME_MISSING` | Missing asset name |
| `IMPORT_COLUMN_CATEGORY_NOT_FOUND` | Column "{column}": category "{value}" not found |
| `IMPORT_COLUMN_FIELD_REQUIRED` | Column "{column}": the field is required |
| `IMPORT_COLUMN_FIELD_SHAPE` | Column "{column}": the value does not fit the field the column is mapped to |
| `IMPORT_COLUMN_LOCATION_NOT_FOUND` | Column "{column}": location "{value}" not found |
| `IMPORT_COLUMN_NOT_A_NUMBER` | Column "{column}": "{value}" is not a number |
| `IMPORT_COLUMN_NOT_IN_OPTIONS` | Column "{column}": "{value}" is not one of the choices: {options} |
| `IMPORT_COLUMN_NOT_YES_NO` | Column "{column}": "{value}" is not yes or no |
| `IMPORT_COLUMN_QUANTITY_BLANK` | Column "{column}": the quantity is empty. Fill it in, or clear the quantity mapping to import every row as 1 |
| `IMPORT_COLUMN_REASON` | Column "{column}": {reason} |
| `IMPORT_DATE_INVALID` | Column "{column}": "{value}" is not a date |
| `IMPORT_FIELD_REQUIRED_NO_COLUMN` | Field "{field}" is required and the sheet has no column for it |
| `IMPORT_FIELD_REQUIRED_UNREADABLE` | Field "{field}" is required and cannot be read from a cell |
| `IMPORT_LINE_NAME_MISSING` | Missing product name |
| `IMPORT_LOCATION_NOT_FOUND` | No location is named “{value}” |
| `IMPORT_LOCATION_UNRESOLVED` | Could not resolve storage location |
| `IMPORT_ONLY_DRAFT` | Can only import lines to DRAFT documents |
| `IMPORT_PRICE_INVALID` | Column "{column}": "{value}" is not a price |
| `IMPORT_QUANTITY_NOT_POSITIVE` | Column "{column}": the quantity has to be greater than zero, "{value}" is not |
| `IMPORT_ROW_FAILED` | The row could not be imported |
| `IMPORT_TOO_MANY_ROWS` | The file has {count} rows; the limit is {limit}. Split it into smaller files. |
| `IMPORT_UNKNOWN_UNIT` | Column "{column}": unknown unit "{value}". Known units: {units} |
| `INGREDIENT_DEFAULTS_UNREADABLE_FILE` | The file could not be read. The import expects a .json or .csv file with one row per ingredient. |
| `INSUFFICIENT_QUANTITY` | Not enough stock to perform this action |
| `INTERNAL_ERROR` | An internal error occurred |
| `INVALID_COUNTRY_CODE` | Country must be a two-letter ISO 3166-1 alpha-2 code (e.g. PL). |
| `INVALID_CURRENCY_CODE` | Currency must be a valid ISO 4217 code (e.g. PLN). |
| `INVALID_EMAIL` | Invalid email format |
| `INVALID_INPUT` | Invalid input |
| `INVALID_MAPPING_JSON` | Invalid mapping JSON |
| `INVALID_PARTNER_TYPE` | This partner type is not recognized. |
| `INVALID_PRINT_PAGE_SIZE` | Paper size must be A4 or Letter. |
| `INVALID_RESET_TOKEN` | Invalid or expired reset token |
| `INVALID_ROLE` | Invalid role. Allowed: {roles} |
| `INVALID_TEMPLATE_MODULE` | Module must be "{module}" |
| `INVALID_TIMEZONE` | Timezone must be a valid IANA zone name (e.g. Europe/Warsaw). |
| `INVALID_URL_MISSING_HOST` | Invalid URL: missing host |
| `INVALID_URL_SCHEME` | Invalid URL: must start with http:// or https:// |
| `INVALID_UUID` | Invalid UUID format |
| `INVITATION_CODE_INVALID` | Invalid or expired invitation code |
| `INVITATION_NOT_FOUND` | Invitation not found |
| `INVITATION_OTHER_ADDRESS` | This invitation was issued for a different email address |
| `ITEM_ALREADY_DELETED` | Item is already deleted |
| `ITEM_CURRENCY_MISMATCH` | Item currency ({item_currency}) must match organization currency ({organization_currency}) |
| `ITEM_NOT_DELETED` | Item is not deleted |
| `ITEM_NOT_FOUND` | Item not found |
| `ITEM_PURGE_REASON_REQUIRED` | A reason is required for permanent deletion in production |
| `ITEM_PURGE_REQUIRES_ARCHIVED` | Only archived items can be purged |
| `ITEM_QUANTITY_ABOVE_CEILING` | The quantity {quantity} is past what the column holds — the largest storable value is {ceiling} |
| `ITEM_QUANTITY_RAISE_IN_VIRTUAL_LOCATION` | This product stands in {location}, where stock is not counted — move it back to a shelf first, then add to it |
| `ITEM_RESTORE_QUANTITY_UNKNOWN` | Cannot restore item: the original quantity is unknown because the deletion history does not hold it |
| `ITEM_UNIT_CANNOT_BE_REMOVED` | The unit {unit} cannot be removed: a quantity without a unit says nothing. Choose another unit instead. |
| `ITEM_UNIT_CHANGE_BLOCKED_BY_STOCK` | This record holds {quantity} {current_unit}. Changing the unit to {new_unit} would relabel that number without changing what is on the shelf. Use it up or write it off first, or record the new unit on a separate record. |
| `ITEM_UNIT_DIFFERS_FROM_TEMPLATE_CONFIRMATION_REQUIRED` | {product} is kept in {template_unit}, and this quantity is given in {chosen_unit}. It will be converted into {template_unit} when saved, so confirm that {chosen_unit} is the unit you meant, or enter the quantity in {template_unit}. |
| `ITEM_UNIT_NOT_CONVERTIBLE_TO_CARD` | {product} is kept in {template_unit}, and a quantity in {chosen_unit} cannot be converted into it. Enter the quantity in {template_unit} — or, for pieces, record on the product how much one piece weighs or holds. |
| `LABEL_ALREADY_ASSIGNED` | Label already assigned |
| `LABEL_IN_USE_BY_PRODUCT` | Cannot delete a label assigned to an active product. Delete the product first. |
| `LABEL_NOT_FOUND` | Label not found |
| `LABEL_SIZE_INVALID` | A label height and width must be > 0. |
| `LINE_TARGET_ALREADY_RECEIVED` | This line was already received in the open receiving session; its goods stay on the shelf they were received to |
| `LINE_TARGET_RECEIPT_ONLY` | A destination can be named on receipt lines only — dispatch and transfer lines take their shelves from the document |
| `LLM_BASE_URL_LOOPBACK` | AI connection base URL targets a loopback hostname ({host}). External URLs only — ask whoever runs this installation to allow a local model server (the LLM_ALLOW_PRIVATE_NETWORKS setting). |
| `LLM_BASE_URL_NO_HOSTNAME` | AI connection base URL must include a hostname. |
| `LLM_BASE_URL_PRIVATE` | AI connection base URL targets a private or internal address ({host}). External URLs only — ask whoever runs this installation to allow a local model server (the LLM_ALLOW_PRIVATE_NETWORKS setting). |
| `LLM_BASE_URL_REFUSED` | AI connection base URL was refused. External URLs only — Set LLM_ALLOW_PRIVATE_NETWORKS=true on self-hosted installs to allow a local model server. |
| `LLM_BASE_URL_REQUIRED_FOR_HTTP_PROVIDER` | This provider is reached over HTTP, so the base URL is required — for example https://openrouter.ai/api/v1 |
| `LLM_BASE_URL_SCHEME` | AI connection base URL must use http or https. |
| `LLM_BASE_URL_UNRESOLVED` | AI connection base URL hostname "{host}" could not be resolved — check the spelling, a typo here reads as an unreachable provider. If the address is spelled right, ask whoever runs that server whether the name is published in DNS. |
| `LLM_CONNECTION_TEST_FAILED` | The connection test could not be completed. Check the address and try again. |
| `LOCATION_ARCHIVED` | '{name}' is archived — restore it first, or choose a location the lists still show |
| `LOCATION_CHAIN_STEP_INCOMPLETE` | Each step of a location chain needs an id or a name. |
| `LOCATION_NOT_INTERNAL` | '{name}' is a virtual location — goods can only be put away in real storage locations |
| `MARGIN_NEGATIVE` | The margin must be 0% or more |
| `MARGIN_TOO_HIGH` | The margin must be below 100% to give a finite price |
| `MEAL_PLAN_EMPTY` | Cannot generate a shopping list from an empty plan |
| `MEAL_PLAN_END_BEFORE_START` | The end date must not be before the start date |
| `MEAL_PLAN_NO_SLOTS` | Enable at least one meal slot |
| `MEAL_PLAN_START_IN_PAST` | Target start date must not be in the past |
| `MEAL_PLAN_TOO_LONG` | Plan cannot exceed {days} days |
| `MEMBER_ROLE_EXACTLY_ONE` | Provide exactly one of role or role_id |
| `META_DATA_SPELLED_TWICE` | 'meta_data' and 'metadata' name one field spelled twice. Send one of them. |
| `MODULES_NOT_ENABLED` | Module '{module_name}' is not enabled for this organization |
| `MODULES_NO_ORGANIZATION` | User not associated with any organization |
| `MODULE_DEPENDENCY_CYCLE` | Circular dependency detected involving module: '{module}' |
| `MODULE_NEEDS_NEWER_PLATFORM` | Module '{module}' requires Inventari {required} or newer; this is version {current}. |
| `NOT_AN_EQUIPMENT_MODEL` | Not an equipment model |
| `NOT_AUTHENTICATED` | Not authenticated |
| `NOT_FOUND` | Resource not found |
| `NO_FIELDS_TO_UPDATE` | No fields to update |
| `NO_LABELS_AVAILABLE` | No labels available for printing |
| `NO_MISSING_INGREDIENTS` | No missing ingredients to add |
| `NO_VALID_IMAGES` | No valid images provided |
| `ONBOARDING_MODULES_NOT_OFFERED` | The profile '{profile}' does not offer these modules: {modules} |
| `ONBOARDING_PROFILE_UNKNOWN` | Unknown profile: '{profile}' |
| `ONLY_IMAGE_FILES_ALLOWED` | Only image files are allowed (jpg, png, gif, webp) |
| `ORGANIZATION_CURRENCY_MISSING` | Organization currency not configured |
| `ORGANIZATION_INVITE_INVALID` | This invitation can't be used. Check that you are registering with the e-mail address it was sent to, or ask for a new one. |
| `ORGANIZATION_NOT_FOUND` | Organization not found |
| `ORGANIZATION_REQUIRED` | Organization required |
| `OVER_RECEIPT_PAST_CEILING` | Receiving {quantity} against {basis} goes past the {ceiling}% over-receipt ceiling — nobody may receive that much |
| `PACKING_DOCUMENT_NOT_OPEN` | Packages can be changed only while the dispatch is confirmed and not yet completed. A completed dispatch keeps its packages as they were shipped. |
| `PACKING_EXCEEDS_DONE` | {name}: the packages hold {packed}, more than the {done} this dispatch ships. Take the difference out of the packages first, or complete with the quantity they hold. |
| `PACKING_EXCEEDS_PICKED` | {name}: only {remaining} picked and not yet packed. A package holds what was picked, and nothing that is already in another package. |
| `PACKING_NOTHING_TO_PACK` | Everything picked is already packed, so there is nothing left for a new package. |
| `PACKING_NOT_A_DISPATCH` | Only a dispatch is packed: packages hold goods leaving the warehouse. |
| `PACKING_NO_PACKAGES` | This dispatch has no packages yet, so there is no packing slip to print. Pack it first. |
| `PACKING_SCAN_NOT_IN_DOCUMENT` | {name} is not on this dispatch, so it does not go in its packages. |
| `PACKING_SCAN_UNRECOGNIZED` | No product carries the code {code}. Scan the product's own barcode, or tap its line to pack it. |
| `PAGINATION_CURSOR_INVALID` | Invalid or expired pagination cursor |
| `PARTNER_CODE_EXISTS` | Partner with code "{code}" already exists. |
| `PARTNER_DELETE_OPEN_PURCHASE_ORDERS` | Cannot delete partner: {count} open purchase order(s) reference this partner |
| `PARTNER_HAS_NO_EMAIL` | The partner has no email address. |
| `PARTNER_NAME_EXISTS` | Partner with name "{name}" and type "{partner_type}" already exists. |
| `PARTNER_NOT_FOUND` | Partner not found |
| `PASSWORD_NEEDS_DIGIT` | Password must contain at least one digit |
| `PASSWORD_NEEDS_LOWERCASE` | Password must contain at least one lowercase letter |
| `PASSWORD_NEEDS_UPPERCASE` | Password must contain at least one uppercase letter |
| `PASSWORD_TOO_LONG` | Password may be at most {max_bytes} bytes long |
| `PASSWORD_TOO_SHORT` | Password must be at least 8 characters |
| `PASTED_TEXT_UNREADABLE` | The pasted text could not be read as a table. Paste rows copied from a spreadsheet, with the same number of columns in each. |
| `PASTE_EMPTY` | No rows to import — paste at least a header row and one data row |
| `PDF_GENERATION_FAILED` | PDF generation failed |
| `PERIOD_ALREADY_CLOSED` | Period {period} is already closed. |
| `PERIOD_NOT_CLOSED` | Period {period} is not closed. |
| `PICKING_LOT_NO_LONGER_AVAILABLE` | Cannot close picking: lot {lot} can no longer give the {quantity} units picked from it |
| `PICKING_TERMINATE_REASON_INVALID` | Invalid terminate reason: {reason} |
| `PIECE_UNIT_MISSING_FROM_CATALOGUE` | This installation's unit catalogue has no piece unit, so 'a quantity of what' has no answer. Name a unit explicitly, or restore the standard unit catalogue. |
| `PO_ALREADY_CANCELLED` | This purchase order is already cancelled |
| `PO_APPROVAL_RACE_CONDITION` | The approval request could not be created — it may have been handled by another action. Try again. |
| `PO_APPROVAL_WORKFLOW_MISSING` | This purchase order needs an approval, but nobody has been set up to give it yet. Ask your administrator to set it up. |
| `PO_CANCEL_COMPLETED` | Cannot cancel a completed purchase order |
| `PO_CANCEL_RECEIVED_QUANTITIES` | Cannot cancel this purchase order because quantities have been received — cancel the linked receipts first |
| `PO_CONFIRM_INVALID_STATUS` | This purchase order cannot be confirmed in its current state. |
| `PO_EMAIL_INVALID_ADDRESS` | Invalid partner email address: {email} |
| `PO_EMAIL_INVALID_STATUS` | Cannot send email for a purchase order in status {status}. Only CONFIRMED or COMPLETED are allowed. |
| `PO_HAS_NO_PARTNER` | This purchase order has no supplier to send it to. |
| `PO_IMPORT_NOT_DRAFT` | Can only import lines to DRAFT purchase orders |
| `PO_LINES_RECEIVED` | Cannot update lines: some items have already been received. Cancel the linked receipt documents first. |
| `PO_LINE_NOT_FOUND` | Purchase order line {po_line_id} not found |
| `PO_LINE_PRODUCT_TEMPLATE_NOT_FOUND` | Product template {template_id} not found |
| `PO_PARTNER_INACTIVE` | Cannot confirm the purchase order: partner "{name}" is inactive |
| `PO_PARTNER_NOT_SUPPLIER` | Cannot confirm the purchase order: partner "{name}" has type "{partner_type}", which is not a supplier type |
| `PO_PDF_INVALID_STATUS` | PDF can only be generated for CONFIRMED or COMPLETED purchase orders. Current status: {status} |
| `PO_RECEIPT_REQUIRES_CONFIRMED` | Only CONFIRMED purchase orders can create a receipt |
| `PO_RECEIVE_QUANTITY_EXCEEDS` | Quantity {quantity} exceeds the remaining {remaining} for line {line} |
| `PO_SUPPLIER_REQUIRED` | A purchase order cannot be confirmed without a supplier |
| `PO_UPDATE_NOT_DRAFT` | Only DRAFT purchase orders can be updated |
| `PRICELIST_MIN_QUANTITY_NOT_POSITIVE` | min_quantity must be > 0, got {min_quantity} |
| `PRICELIST_UNIT_PRICE_NOT_POSITIVE` | unit_price must be > 0, got {unit_price} |
| `PRICELIST_VALID_TO_BEFORE_VALID_FROM` | valid_to ({valid_to}) must be >= valid_from ({valid_from}) |
| `PRINT_JOB_NOTHING_TO_PRINT` | Nothing to print: none of the chosen labels was found |
| `PRINT_JOB_ONE_TARGET` | Send exactly one kind of label: pool labels by id, pool labels by code, or storage locations. |
| `PRODUCTION_ACTUAL_QTY_MUST_BE_POSITIVE` | The produced quantity must be greater than zero. |
| `PRODUCTION_CANCEL_NOT_DRAFT` | This production order already has status {status} — only a draft can be cancelled. |
| `PRODUCTION_COMPLETE_NOT_DRAFT` | This production order already has status {status} — only a draft can be completed. |
| `PRODUCTION_NO_RECIPE` | No BOM for this product — create a BOM first |
| `PRODUCTION_OVERPRODUCTION_DISABLED` | Overproduction is disabled in settings — this order cannot produce more than planned. |
| `PRODUCTION_RECIPE_NOT_FOUND` | BOM {recipe_id} not found in this organization |
| `PRODUCTION_RECIPE_PRODUCT_MISMATCH` | This BOM does not belong to this product |
| `PRODUCTION_REVERSE_NOT_COMPLETED` | This production run is {status}, so there is nothing to take back — only a completed run can be undone. |
| `PRODUCTION_REVERSE_OUTPUT_USED` | This run cannot be undone: some of what it made has already left its location. Record a stock correction for what is left instead. |
| `PRODUCTION_UPDATE_NOT_DRAFT` | This production order already has status {status} — only a draft can be edited. |
| `PRODUCT_LABEL_NO_CODE` | Nothing to print: none of the chosen products has a code. Generate one on the product form |
| `PRODUCT_LABEL_TOO_NARROW` | The code {code} does not fit a label {width} mm wide: its bars need one at least {needed} mm wide. Choose a wider label size |
| `PRODUCT_LABEL_TOO_SHORT` | The label {height} mm tall is too short: after the name and the text, the bars of the code {code} are left too little height for a scanner to read. Choose a taller label size |
| `PRODUCT_TEMPLATE_NOT_FOUND` | Product template not found |
| `PURCHASE_ORDER_NOT_FOUND` | Purchase order not found |
| `PUTAWAY_CAPACITY_EXISTS` | This location already has a capacity for this product — edit the existing entry instead. |
| `PUTAWAY_NEEDS_ANOTHER_LOCATION` | The goods already stand there: choose the location they go to. |
| `PUTAWAY_RULE_NEEDS_LOCATION` | A putaway rule needs at least one location. |
| `PUTAWAY_RULE_NEEDS_MATCH_KEY` | A putaway rule needs at least one condition — a product, a category, a context tag or a storage type. |
| `PUTAWAY_SHELF_SCAN_REQUIRED` | Scan the shelf label before the goods go on it. |
| `PUTAWAY_UNKNOWN_CONTEXT_TAG` | Unknown category group '{value}' — choose one that an existing category defines |
| `PUTAWAY_UNKNOWN_STORAGE_TYPE` | Unknown storage type '{value}' — choose one of the organization's storage types |
| `RATING_MUST_BE_1_TO_5` | Rating must be between 1 and 5 |
| `REASON_BLANK` | The reason must not be blank |
| `RECEIPT_NEEDS_QUARANTINE_LOCATION` | The receipt includes damaged goods or goods on a quality hold, but the document profile names no quarantine location. Set one in the document settings. |
| `RECEIPT_NEEDS_TARGET_LOCATION` | The receipt document has no target location. |
| `RECEIVING_MODE_NEEDS_A_WAREHOUSE` | Only a top-level location chooses how it receives. |
| `RECIPE_COLLECTION_NOT_FOUND` | Collection not found |
| `RECIPE_COLLECTION_OWN_PARENT` | A collection cannot be its own parent |
| `RECIPE_COLLECTION_PARENT_NOT_FOUND` | Parent collection not found |
| `RECIPE_COLLECTION_UNDER_DESCENDANT` | A collection cannot be moved under its descendant |
| `RECIPE_EXTRACTION_FAILED` | The recipe could not be extracted from this page. Try again, or enter the recipe by hand. |
| `RECIPE_IMPORT_DATA_REQUIRED` | data required for json import |
| `RECIPE_IMPORT_NAME_REQUIRED` | name is required in import data |
| `RECIPE_IMPORT_UNIT_UNKNOWN` | Ingredient '{ingredient}' uses the unit '{unit}', which this instance does not know |
| `RECIPE_IMPORT_URL_REQUIRED` | url required for url import |
| `RECIPE_INGREDIENT_UNIT_MISSING` | Ingredient '{ingredient}' has an amount but no unit |
| `RECIPE_NOT_FOUND` | Recipe not found |
| `RECIPE_SCRAPE_EMPTY` | Jina Reader returned empty content for {url} |
| `RECIPE_SCRAPE_ENCODING_UNSUPPORTED` | Jina Reader returned compressed content that cannot be read safely. Try another import method. |
| `RECIPE_SCRAPE_FAILED` | Failed to scrape recipe from URL |
| `RECIPE_SCRAPE_FETCH_FAILED` | Jina Reader fetch failed for {url}: {error} |
| `RECIPE_SCRAPE_NO_INGREDIENTS` | The AI found no ingredients — the page may not be a recipe |
| `REGISTER_DATE_FROM_AFTER_DATE_TO` | The start date must not be after the end date |
| `RELOCATION_BLOCKED_BY_RESERVATIONS` | Cannot move item: source stock has outstanding reservations. Release or fulfill them first. |
| `RELOCATION_DESTINATION_FOREIGN` | Cannot move item: the destination is not this organization. |
| `REMOVAL_STRATEGY_OF_SHARED_PRODUCT` | This product comes from the shared catalogue, so the order its stock leaves in is the catalogue's and cannot be changed for one organization. |
| `REORDER_MAX_BELOW_MIN` | max_quantity ({max_quantity}) must be >= min_quantity ({min_quantity}) |
| `REORDER_MIN_QUANTITY_NEGATIVE` | min_quantity must be >= 0, got {min_quantity} |
| `REORDER_RULE_NOT_FOUND` | Reorder rule not found |
| `REORDER_SAFETY_STOCK_NEGATIVE` | safety_stock must be >= 0, got {safety_stock} |
| `REPLENISHMENT_NOTHING_TO_MOVE` | There is nothing to carry from reserve: the shelf no longer has the stock, or the pick face no longer needs it. |
| `REPLENISHMENT_SHELF_SCAN_MISMATCH` | That code names another shelf: scan the reserve location the goods are taken from. |
| `REPLENISHMENT_SHELF_SCAN_REQUIRED` | Scan the reserve location you are taking the goods from. |
| `ROLE_NAME_TAKEN` | A role named "{name}" already exists in this organisation. |
| `ROLE_NOT_FOUND` | Role not found |
| `ROLE_NOT_IN_ORGANIZATION` | Role does not belong to this organization |
| `ROLE_OTHER_ORGANIZATION` | Role belongs to a different organization |
| `SEARCH_QUERY_EMPTY` | Type something to search for |
| `SERIAL_NUMBER_EXISTS` | Serial number already exists: {serial_number} |
| `SETTINGS_FIELD_REQUIRED` | The setting '{field}' is required |
| `SETTINGS_FIELD_UNKNOWN` | Unknown setting '{field}' |
| `SETTINGS_NUMBER_TOO_LARGE` | The setting '{path}' must be at most {limit}, got {value} |
| `SETTINGS_NUMBER_TOO_SMALL` | The setting '{path}' must be at least {limit}, got {value} |
| `SETTINGS_PAYLOAD_NOT_OBJECT` | The settings must be sent as a JSON object |
| `SETTINGS_TEXT_TOO_LONG` | The setting '{path}' must be at most {limit} characters long |
| `SETTINGS_TEXT_TOO_SHORT` | The setting '{path}' must be at least {limit} characters long |
| `SETTINGS_VALUE_NOT_ALLOWED` | The setting '{path}' must be one of: {allowed} (got {value}) |
| `SETTINGS_VALUE_NOT_ARRAY` | The setting '{path}' must be a list |
| `SETTINGS_VALUE_NOT_BOOLEAN` | The setting '{path}' must be true or false |
| `SETTINGS_VALUE_NOT_INTEGER` | The setting '{path}' must be a whole number |
| `SETTINGS_VALUE_NOT_NUMBER` | The setting '{path}' must be a number |
| `SETTINGS_VALUE_NOT_OBJECT` | The setting '{path}' must be an object |
| `SETTINGS_VALUE_NOT_STRING` | The setting '{path}' must be text |
| `SHEET_UNREADABLE` | This file could not be read as a spreadsheet. Check that it is a valid .xlsx or .csv file and try again. |
| `SHOPPING_LIST_ITEM_CATEGORY_UNKNOWN` | Unknown category (category_id: {category_id}) — the category does not exist |
| `SHOPPING_LIST_ITEM_ITEM_UNKNOWN` | Unknown product (item_id: {item_id}) — the item does not exist |
| `SHOPPING_LIST_ITEM_QUANTITY_ABOVE_CEILING` | The quantity {quantity} is past what the column holds — the largest storable value is {ceiling} |
| `SHOPPING_LIST_ITEM_QUANTITY_ROUNDS_TO_ZERO` | Quantity {quantity} rounds to zero at the store's precision — the smallest countable amount is {smallest} |
| `SHOPPING_LIST_ITEM_TEMPLATE_UNKNOWN` | Unknown product template (template_id: {template_id}) — the template does not exist |
| `SHOPPING_LIST_ITEM_UOM_UNKNOWN` | Unknown unit of measure (uom_id: {uom_id}) — the unit does not exist |
| `SHOPPING_LIST_NOTHING_TO_CONVERT` | No convertible items (all lack a product template) |
| `SHORT_CODES_TAKEN` | short_code(s) already in use in this org: {codes} |
| `SHORT_CODE_DUPLICATE_IN_REQUEST` | Duplicate short_code in request: {short_code} |
| `SHORT_CODE_INVALID_FORMAT` | Invalid code format |
| `SKU_FORMAT_INVALID` | SKU may contain only letters, digits, dashes, underscores and slashes |
| `SKU_IN_USE` | SKU {sku} already belongs to another product |
| `SMTP_CONFIG_INVALID` | The email server settings are not valid: {reason} |
| `SMTP_NOT_CONFIGURED` | This organization has no email sending configured |
| `STOCK_AS_OF_BEFORE_LEDGER` | The movement ledger starts on {starts_at}. Nothing is known before that — not zero — so a report for {as_of} would be a guess. |
| `STOCK_AS_OF_NO_HISTORY` | This organization records no stock movements, so it has no history to report on. Today’s stock levels are the only answer it can give. |
| `STOCK_AS_OF_PDF_TOO_MANY` | This report has {total} products — more than the {limit} rows a printout carries. Export it as a spreadsheet instead, or pick one location to narrow it. |
| `STOCK_INSUFFICIENT_FOR_TEMPLATE` | Insufficient stock for template {template_id}: requested {requested}, available {available} |
| `STOCK_INSUFFICIENT_RECORD` | Insufficient stock for "{item}": available {available}, requested {requested}. |
| `STOCK_LOT_NOT_CONSUMABLE` | Batch {lot} is {status} and cannot be consumed or reserved |
| `STOCK_MOVES_EXPORT_TOO_MANY` | {total} movements match — more than the {limit} one sheet carries. Narrow the dates, the place or the product and export again. |
| `STOCK_PRODUCT_NOT_FOUND` | The product {product} was not found. |
| `STOCK_RECORD_NOT_FOUND` | The record {item} was not found. |
| `STOCK_RESERVED_OVER_QUANTITY` | That would hold more of these goods than are on the shelf. Release a reservation, or count the shelf again. |
| `STOCK_TAKE_ACTIVE_FOR_LOCATION` | An active stock take already exists for this storage location |
| `STOCK_TAKE_BULK_ITEM_ID_REQUIRED` | item_id is required for bulk count operations |
| `STOCK_TAKE_CLOSE_REQUIRES_FINALIZE` | A stock take is closed by finalising it (POST /stock-takes/{id}/complete), not by a status change |
| `STOCK_TAKE_DELETE_COMPLETED` | Can only delete draft or active stock takes |
| `STOCK_TAKE_EDIT_COMPLETED` | Cannot edit a completed or cancelled stock take |
| `STOCK_TAKE_ITEM_NOT_FOUND` | Stock take item not found |
| `STOCK_TAKE_NOT_ACTIVE` | Stock take is not active |
| `STOCK_TAKE_NOT_FOUND` | Stock take not found |
| `STOCK_TAKE_STATUS_UNCHANGEABLE` | Cannot change status from {current} to {new}. |
| `STOCK_TAKE_TOLERANCE_NOT_ALLOWED` | Accepting a difference beyond the tolerance needs the stock take approval permission. |
| `STOCK_TAKE_UNCOUNTED_ITEMS` | {count} uncounted items remaining |
| `STORAGE_ARCHIVED` | This location is archived. Restore it before storing products here. |
| `STORAGE_ARCHIVE_BLOCKED_BY_ITEMS` | Cannot archive: {count} item(s) are still stored here. Move them first or archive with a target location. |
| `STORAGE_ARCHIVE_TARGET_ARCHIVED` | Cannot move items into an archived location. |
| `STORAGE_ARCHIVE_TARGET_IS_DESCENDANT` | Cannot move items into a descendant of the location being archived. |
| `STORAGE_ARCHIVE_TARGET_IS_SELF` | Cannot move items into the location being archived. |
| `STORAGE_CODE_NUMBER_NOT_HERE` | Only an ordinary location can be numbered, not an archived or virtual one |
| `STORAGE_CODE_PARENT_NOT_NUMBERED` | This location cannot be numbered on its own: the places above it do not carry their template codes yet, or it is deeper than the template goes. Number the level above it first |
| `STORAGE_CODE_TEMPLATE_INVALID` | The code template '{template}' cannot be used. Write placeholders such as {{zone}}-{{rack:02}}-{{level:02}}, with a separator between them, or a prefix of up to five letters and digits such as LOC |
| `STORAGE_CODE_TEMPLATE_NOT_TREE` | This warehouse draws random codes: give it a template with placeholders, such as {zone}-{rack:02}-{level:02}, before numbering its locations |
| `STORAGE_CODE_TEMPLATE_NOT_WAREHOUSE` | A code template belongs to a warehouse, a location at the top of the tree |
| `STORAGE_DELETE_BLOCKED_BY_CHILD_NAME` | Cannot delete storage location "{location}": its child location "{name}" would end up beside another location with the same name once it moves up a level. Rename one of them first. |
| `STORAGE_DELETE_BLOCKED_BY_MOVEMENTS` | Cannot delete storage location: {count} stock movements reference it. The movement history is immutable — archive this location instead. |
| `STORAGE_DELETE_BLOCKED_BY_REFERENCES` | Cannot delete storage location: it is still referenced by other records (constraint "{constraint}"). Archive it instead. |
| `STORAGE_DELETE_BLOCKED_BY_STOCK` | Cannot delete storage location: the stock register still holds stock here with no record standing on it. Archive this location instead, or bring its stock back to a record first. |
| `STORAGE_DELETE_CONCURRENT_MOVEMENTS` | Cannot delete storage: a concurrent transaction created stock movements referencing it. Retry to refresh the count. Original error: {error} |
| `STORAGE_DELETE_FAILED_ITEMS` | Cannot delete a storage location that contains items. Move or delete them first. |
| `STORAGE_LOCATION_AMBIGUOUS` | "{text}" matches {count} storage locations ({shown}). Name the path instead, for example "{example}". |
| `STORAGE_NOT_FOUND` | Storage location not found |
| `STORAGE_NO_SHORT_CODE` | Storage has no short code. Generate one first. |
| `STORAGE_OWN_PARENT` | A location cannot be its own parent. |
| `STORAGE_RESTORE_PARENT_ARCHIVED` | Cannot restore into an archived parent location. Restore the parent first. |
| `STORAGE_TYPE_EXISTS` | A storage location type with this code already exists |
| `STORAGE_TYPE_IN_USE` | Storage location type is in use by {count} locations |
| `STORAGE_USAGE_IMMUTABLE` | A storage location's purpose is set by the system and cannot be changed. |
| `STORAGE_VANISHED_DURING_BATCH` | Storage location {location} vanished during the batch. |
| `TEMPLATE_IMPORT_INVALID_FIELD` | The field "{field}" is missing or is not valid. |
| `TEMPLATE_IMPORT_NOT_JSON` | The file could not be read as a template export — it is not valid JSON. |
| `TEMPLATE_IMPORT_NOT_RENDERABLE` | The template could not be rendered: {detail} |
| `TEMPLATE_IMPORT_UNKNOWN_PLACEHOLDERS` | The template references fields that do not exist: {placeholders}. |
| `TEMPLATE_IMPORT_WRONG_KIND` | This file is not an exported document template. |
| `TEMPLATE_IMPORT_WRONG_VERSION` | The file was exported in format version {version}; this installation reads version {supported}. |
| `TEMPLATE_IN_USE_BY_ITEMS` | Cannot delete template: it is used by {count} item(s) |
| `TEMPLATE_NOT_BUILTIN_COPY` | This template was not copied from a built-in layout |
| `TEMPLATE_OTHER_ORGANIZATION` | Template belongs to a different organization |
| `TOKEN_INVALID` | Invalid authentication token |
| `TRANSFER_CANNOT_SPLIT_SERIALIZED_RECORD` | A transfer cannot split the serialized record {serial_number}; transfer the whole record. |
| `TRANSFER_MORE_THAN_THE_RECORD_HOLDS` | The record "{item_name}" holds {available} and the line moves {requested}. Lower the line, or move the rest from another record. |
| `TRANSFER_NEEDS_TARGET_LOCATION` | The transfer document has no target location. |
| `UNIT_WEIGHT_OF_SHARED_PRODUCT` | This product comes from the shared catalogue, so the weight of one piece is the catalogue's and cannot be changed for one organization. |
| `UNKNOWN_BULK_ACTION` | Unknown bulk action: {action} |
| `UNSUPPORTED_EXPORT_FORMAT` | Unsupported export format: {format} |
| `UNSUPPORTED_IMPORT_FORMAT` | Unsupported import format: {format} |
| `UOM_CONVERSION_UNAVAILABLE` | Quantity in {unit} cannot be converted to the stock unit {stock_unit} |
| `UOM_NOT_FOUND` | Unit not found |
| `UOM_QUANTITY_NON_NEGATIVE` | Quantity must be non-negative |
| `UOM_QUANTITY_REQUIRES_WHOLE_NUMBER` | The unit {unit} takes whole numbers only, so {quantity} cannot be saved. Round the quantity to a whole number. |
| `UOM_QUANTITY_TOO_MANY_DECIMAL_PLACES` | The unit {unit} takes at most {places} decimal place(s), so {quantity} cannot be saved. Round the quantity to that precision. |
| `URL_MUST_BE_PUBLIC` | URL must point to a public host |
| `USER_BLOCKED` | Your account has been blocked. Reason: {reason} |
| `USER_EMAIL_REQUIRED` | This account has no email address, so it has no assets to show. |
| `USER_HAS_NO_ORGANIZATION` | User has no organization |
| `USER_NOT_FOUND` | User not found |
| `USER_NOT_IN_ORGANIZATION` | User does not belong to this organization |
| `USE_BY_NEEDS_OPEN_PACKAGE` | The record "{item_name}" is sealed, so it has no use-by to set. Open it first; until then it is judged by the batch's date. |
| `USE_PARTIALLY_MORE_THAN_LEFT` | The record "{item_name}" holds {available} of this package and {requested} was given as left. Say how much is left, which cannot be more than there is. |
| `USE_PARTIALLY_NEEDS_COUNTED_UNIT` | "{item_name}" is kept in a measured unit, so there is no package to open. Take what you use from the quantity. |
| `USE_PARTIALLY_PACK_HAS_NO_MEASURE` | "{item_name}" is counted in packs and the product does not say how much one holds, so only "opened" or "finished" can be recorded. |
| `USE_PARTIALLY_SERIALIZED` | The serialized record {serial_number} cannot be opened and split; use it whole. |
| `VISION_AI_NOT_CONFIGURED` | No AI connection has been chosen for image recognition yet. Choose one in Settings → AI Connections. |
| `VISION_UNSUPPORTED_IMAGE_TYPE` | The file "{filename}" is not an accepted image type ({content_type}). Accepted: {accepted}. |
| `WEBHOOK_URL_MALFORMED` | This is not a valid web address. Enter a full address such as https://example.com/hook. |
| `WEBHOOK_URL_NO_HOSTNAME` | The webhook address must include a host name, for example https://example.com/hook. |
| `WEBHOOK_URL_SCHEME` | Only {schemes} addresses are allowed for webhooks. |
| `WMS_BARCODE_REQUIRED` | Scan a barcode first. |
| `WMS_CANCEL_SESSION_IS_PACKED` | {name}: a package already holds {packed} of what was picked. Take it out of the package first, then cancel the session. |
| `WMS_CANNOT_COMPLETE_DESTINATION_NOT_SCANNED` | The session cannot be completed: the destination location has not been scanned yet. |
| `WMS_CANNOT_COMPLETE_LINES_PENDING` | The session cannot be completed: {count} line(s) are still pending. |
| `WMS_CANNOT_COMPLETE_NO_LINES` | The session cannot be completed: it has no lines. |
| `WMS_DOCUMENT_NOT_CONFIRMED` | The document was not found or is not confirmed. |
| `WMS_DOCUMENT_TYPE_NOT_SUPPORTED` | This session does not handle documents of type {document_type}. |
| `WMS_LINE_DOCUMENT_CLOSED` | Document {number} is {status}, so its lines in this session can no longer be changed. |
| `WMS_LINE_NOT_FOUND` | The session line was not found. |
| `WMS_LINE_NOT_PENDING` | The session line was not found or is no longer pending. |
| `WMS_NOTHING_TO_UNDO` | This line has nothing recorded to undo. |
| `WMS_PICK_DOCUMENT_IN_SESSION` | Document {number} is already being picked in another session (opened by {owner}), so the picking session was not started. |
| `WMS_PICK_DOCUMENT_NOT_CONFIRMED` | Document {number} is not confirmed, so the picking session was not started. Only confirmed documents can be picked. |
| `WMS_PICK_DOCUMENT_NOT_DISPATCH` | Document {number} is not a dispatch, so the picking session was not started. Only dispatches can be picked together. |
| `WMS_PICK_DOCUMENT_NOT_FOUND` | Document {document} was not found in this organization, so the picking session was not started. |
| `WMS_QUANTITY_ABOVE_EXPECTED` | The quantity cannot exceed the expected quantity. |
| `WMS_QUANTITY_CANNOT_BE_NEGATIVE` | The quantity cannot be negative. |
| `WMS_SESSION_HELD_BY_OTHER_USER` | Another user has an active session on this document (opened by {owner}). |
| `WMS_SESSION_NOT_FOUND` | The active session was not found. It may have been completed or cancelled. |
| `WMS_SESSION_NOW_HELD_BY` | This session is now held by {owner}; scans are no longer accepted from here. |
| `WMS_SHORT_BELOW_SCANNED` | The final quantity cannot be below the scanned quantity ({scanned}); to record less, say the count replaces the scans. |
| `WMS_SHORT_PICK_NEEDS_OUTCOME` | A line picked short needs a reason: Shortage owes the rest on a backorder, any other reason closes the gap. |
| `WMS_SKIP_LINE_IS_PACKED` | {name}: a package already holds {packed} of what was picked. Take it out of the package first, then skip the line. |
| `WMS_UNDO_LINE_IS_PACKED` | {name}: a package already holds {packed} of what was picked. Take it out of the package first, then undo the pick. |
| `already_in_focus` | Organization is already focused on '{module}'. |
| `dependency_closure` | Module '{module}' requires '{missing_dependency}', which is not registered. |
| `dependency_cycle` | Circular dependency detected involving module: '{module}' |
| `dependency_cycle` | Circular dependency detected among modules: {modules} |
| `focus_module_always_on` | Module '{module}' is always on and cannot be the single focus. |
| `focus_module_not_allowed` | Module '{module}' is not enabled for this organization. |
| `module_not_allowed` | Modules not allowed for this organization: {not_allowed_modules} |
| `not_in_focus` | Organization is not in single-module focus mode. |
| `unknown_module` | Module '{module}' is not registered. |
| `unknown_module` | Profile references modules that are not registered: {unknown_modules} |
<!-- END GENERATED REFUSAL CODES -->

## 429 Too Many Requests

Rate limits answer with the same coded object as everything else:

```json
{
  "detail": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Too many requests. Try again later.",
    "limit": "10 per 1 minute",
    "lang": "en"
  }
}
```

The response carries the `limit` that was hit in the body. The `message` is in
the request's language whichever limit refused it — a route's own or the
default one, which refuses before the route is reached. The limiter does
not add `X-RateLimit-*` or `Retry-After` headers today; wait before retrying,
because a request retried inside the same window is refused again.

`AI_USAGE_LIMIT_EXCEEDED` is a different 429: the request is not rate-limited,
the organization's configured AI budget is spent. Its fields (see above) say
what was used, against which ceiling, and for which period; retrying sooner
than the next period's start does not help.

## 422 validation errors

FastAPI's validation envelope is a list, one entry per bad field:

```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": ["body", "quantity"],
      "msg": "Input should be greater than 0",
      "input": -1,
      "ctx": {"gt": 0}
    }
  ]
}
```

`loc` is the path to the field (`["body", "line", 2, "quantity"]` for a nested
list), `msg` is the translated sentence where the catalogue carries one, and
`lang` and `code` are added to an entry whose refusal came from a validator
(`ServiceRejectionError`). The frontend's `extractApiError` reads the `msg` of
the first entry, prefixed with the last segment of its `loc`.

## Where the code is written

- `backend/app/core/exceptions.py` — `AppException`, `NotFoundException`,
  `ForbiddenException`, `ConflictException`, `ValidationException`,
  `UnprocessableException`, `TooManyRequestsException`, and the service-error
  mapping.
- `backend/app/main.py` — the global handlers for `ValueError`, `IntegrityError`,
  unhandled exceptions, request validation and LLM failures.
- `backend/app/core/limiter.py` — the 429 handler.
- Each router for its domain's codes.
