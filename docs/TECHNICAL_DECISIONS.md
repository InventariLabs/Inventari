# Technical Decisions & Architecture Design Records (ADR)

This document outlines the key technical decisions made during the development of Inventari. These choices reflect our focus on privacy, performance, and developer productivity.

## 1. Local-First Product Data (The OFF Strategy)

**Decision:** We import Open Food Facts (OFF) data into a separate local PostgreSQL database (`products_db`) rather than relying on external API calls during scanning. The products database is optional (behind the `food` Docker profile) and conditionally enabled via `PRODUCTS_DATABASE_URL`.

**Rationale:**
*   **Privacy:** Most inventory apps leak your purchase history to 3rd party servers. Inventari looks barcodes up in its local catalog, so a scan sends nothing outside your network; only the features that call an external service by design (an AI connection you configure, recipe import through the Jina Reader) do.
*   **Performance:** Local DB lookups take <10ms, while external API calls can take >500ms. This results in a "magical" scanning experience where product data appears instantly.
*   **No internet needed for lookups:** Storage areas often have poor connectivity. Once the local catalog is seeded, barcode lookups need no connection beyond the Inventari server itself; the browser still has to reach that server (there is no offline mode, see §16).

## 2. Sync SQLAlchemy 2.0 with FastAPI ThreadPool *(superseded)*

> **Superseded.** Request handling now uses async SQLAlchemy over `asyncpg` with
> async-only services — see [ADR-006](adr/ADR-006-async-only-service-functions.md).
> The record below is the original
> rationale, kept for history ([ADR-005](adr/ADR-005-sync-sqlalchemy-threadpool.md)).

**Decision:** We use the synchronous SQLAlchemy engine (`psycopg2`) inside FastAPI's `async def` routes instead of a fully asynchronous driver (`asyncpg`).

**Rationale:**
*   **Productivity:** Asynchronous SQLAlchemy introduces significant complexity regarding Lazy Loading and relationships. In a complex logistics engine, the ability to access `item.category.name` without explicit `await` significantly reduces bugs and speeds up development.
*   **Developer Experience:** Our `shell.py` (Shell Plus) works like Django's, allowing instant data inspection without handling event loops manually.
*   **Performance:** For standard RDBMS workloads, synchronous drivers with a well-configured connection pool (PgBouncer in transaction mode) often match or outperform async drivers due to lower overhead.

## 3. Native Asyncio Task Scheduler with Redis Persistence

**Decision:** We use a lightweight in-process scheduler (`app/core/scheduler.py`) backed by Redis Streams instead of Celery or RQ.

**Rationale:**
*   **Simplicity over Celery:** Celery requires a separate message broker (RabbitMQ) and worker processes. Our scheduler runs inside the main FastAPI process for fire-and-forget tasks and uses Redis Streams with Consumer Groups for persistent tasks that must survive restarts.
*   **Dual-mode execution:** Local (in-memory) tasks for ephemeral work; persistent (Redis-backed) tasks for guaranteed execution. This gives us the reliability of a message queue without the operational complexity of a separate worker framework.
*   **Shared infrastructure:** Redis also powers the EventBus, the token blacklist, the rate limiter and a read-through cache — eliminating the need for additional infrastructure.

## 4. Multi-Layered Isolation Strategy

**Decision:** We enforce tenant and module isolation through multiple independent layers — static analysis, runtime session proxying, and organizational scoping — rather than database-native Row-Level Security (RLS).

**Guardrail layers:**

| # | Layer | Mechanism |
|---|-------|-----------|
| 1 | AST import guard | `app/core/architecture_lint/` blocks forbidden imports (`app.models`, `app.database`, `app.services`) in module code |
| 2 | Escape-hatch validation | Direct DB access requires a marker comment with a justification (min 5 words) |
| 3 | CQRS enforcement | Read-only escape-hatch files cannot call `db.commit()`, `db.add()`, `db.delete()`, `db.merge()` (a text check; a file that also writes its own module tables declares `# module_writes:`) |
| 4 | API layer write prohibition | Router files cannot perform direct DB writes to Core tables |
| 5 | Public API model guard | `CoreAPI` public endpoints block raw model imports |
| 6 | AsyncModuleScopedSession | Runtime session proxy auto-filters by `organization_id` and validates tenant ownership on CRUD |
| 7 | `require_org` in routers | Every endpoint must explicitly extract and scope to `organization_id`, except those listed as global by design in `app/core/request_scope_baseline.txt` |

**Rationale:**
*   **Simplicity over RLS:** Application-layer isolation avoids the complexity and debugging overhead of database-native Row-Level Security. SQL queries remain readable and migrations straightforward.
*   **Defense in depth:** The layers are independent, so a miss in one is meant to be caught by another. Only background jobs get a runtime row filter (layer 6); on the request path the static layers and the services carry the tenant scoping, and the tenancy tests are the backstop ([ADR-008](adr/ADR-008-app-layer-isolation-not-rls.md)).
*   **CI enforcement:** The architecture linter runs in CI and blocks PRs that violate module boundaries.

## 5. The "Core vs Module" Philosophy (YAGNI for Logistics)

**Decision:** The core engine provides domain-neutral primitives (Items, Locations, Categories, stock and its movements) and extension points (Interceptors, EventBus, ContributionRegistry). All vertical-specific logic lives in optional modules.

**Current modules (15 backend, 21 frontend):**

Backend: `api_keys`, `approvals`, `equipment`, `example_widgets`, `maker`, `nutrition`, `printing`, `purchase_orders`, `recipes`, `shopping_lists`, `stats`, `stock_takes`, `vision`, `warehouse`, `webhooks` + core.

**Extension mechanisms:**
*   **InterceptorPipeline** (`app/core/interceptors.py`): Synchronous before/after hooks for Item, Storage, and Category CRUD. Modules can mutate data or block operations.
*   **EventBus** (`app/core/events.py`): Asynchronous pub/sub with Redis Streams persistence and Consumer Groups. 28 system events defined (module-owned events live in the modules).
*   **ContributionRegistry** (`app/core/contributions.py`): Extension points for `scan_providers`, `dashboard_widgets`, `quota_providers`, `item_interceptors`, `storage_interceptors`, `category_interceptors`, `upload_path_resolvers`. (Experimental, no consumer yet: `enrichment_providers`, `item_actions`, `settings_panels` — see `MODULES_GUIDE.md`, "Experimental points".)
*   **CoreAPI** (`app/core/public_api/`): 33 namespaces (`core_api.<name>`) covering items, categories, locations, stock, organizations, partners, users, secrets, file storage, and more.

**Rationale:**
*   **Maintainability:** Keeping the core schema small prevents "Core Domain Pollution." Users tracking household inventory aren't burdened with tables for pallet shipping manifests.
*   **User Experience:** B2B features often require strict workflows. By isolating these in modules, we preserve the frictionless "1-click consume" UX for home users.
*   **3-Vertical Test:** Before adding anything to Core, we apply the test: *Would this concept be needed by at least 3 different verticals (e.g., food, equipment, library)?* If no, it belongs in a module.

## 6. One Number of Stock: the Record

**Decision:** `Item.quantity` on a record — one batch of one owner on one shelf — is the only number of stock. A quant is the sum of the records per (product_template, location, lot, owner), read from a view (`stock_quants_from_records`); a numberless anchor per (product_template, location) is the lock. See [ADR-022](adr/ADR-022-one-number-of-stock.md), which superseded the earlier two-number model (ADR-004: a quant table as the truth, `Item.quantity` as its cache, a bridge between them).

**Rationale:**
*   **Accurate inventory accounting:** Physical stock is tracked at the (product × location × lot × owner) grain, supporting reserved/available separation: reservation rows name that grain, and a database guard refuses at commit a hold its records cannot cover.
*   **Nothing to keep in sync:** Every change to a record posts its movement and cost layer in the same transaction; there is no second number to drift from. A reconciliation endpoint (`GET /api/v1/stats/reconciliation`) compares the records with the movement ledger and the cost layers.
*   **WMS readiness:** The records' grain and the anchor lock carry reservations, picking and transfers without a stock table of their own.

## 7. Soft-Delete / Restore / Purge Lifecycle

**Decision:** Items are never hard-deleted by default. The delete operation performs a soft-delete (setting `is_deleted=True`, zeroing quantity, posting the change as a movement). Archived items can be restored or permanently purged.

**API surface:**
*   `DELETE /items/{id}` — soft-delete with an optional free-form reason string (a delete that names none keeps none; values are not constrained by an enum)
*   `POST /items/{id}/restore` — restore to active state
*   `DELETE /items/{id}/purge` — permanent hard delete (only for already-archived items)
*   `GET /items/archived` — list soft-deleted items

**Rationale:**
*   **Safety net:** Accidental deletions are reversible. Users can restore items with full history preservation.
*   **Audit trail:** Deletion reason, timestamp, and user are recorded. History logs both DELETED and RESTORED actions.
*   **Stock integrity:** Soft-delete zeroes the record's quantity — the stock itself — and posts the movement immediately, preventing phantom stock.

## 8. Redis as Infrastructure Backbone

**Decision:** Redis serves as a shared infrastructure component for five distinct subsystems: event bus, task scheduling, token blacklisting, a read-through cache and rate limiting.

**Roles:**
1.  **EventBus persistence** — Redis Streams with Consumer Groups for cross-instance event delivery.
2.  **Scheduler persistent queue** — Guaranteed task execution that survives process restarts.
3.  **Token blacklist** — JWT revocation with fail-open (dev) / fail-closed (prod) modes.
4.  **Read-through cache** — Per-organization data read on many requests (the enabled-module set, units and categories, analytics read-models), invalidated on write. System settings are not cached: every read goes to the database.
5.  **Rate limiter** — Request counters (`app/core/limiter.py`).

**Rationale:**
*   **Single dependency, multiple roles:** One Redis-protocol service (Valkey in the compose stacks; production adds a second, `noeviction` instance, `redis-critical`, for the token blacklist and the rate limiter) replaces what would otherwise require a message broker (RabbitMQ), a separate task queue (Celery), and a cache layer.
*   **Async-native:** Uses `redis.asyncio` client, fitting naturally into FastAPI's async architecture.
*   **Simplicity:** No separate worker processes to manage; Redis operates as a sidecar service alongside PostgreSQL.

## 9. Dual-Token Authentication (JWT + HttpOnly Cookie)

**Decision:** We use a dual-token strategy: short-lived JWT access tokens (in-memory on the client) paired with long-lived refresh tokens stored in HttpOnly cookies.

**Rationale:**
*   **XSS protection:** Refresh tokens in HttpOnly cookies are invisible to JavaScript. Even if XSS occurs, the attacker cannot steal the refresh token.
*   **CSRF protection:** The refresh cookie is `SameSite=Lax`, so a browser does not send it on a cross-site POST; the API keeps no separate CSRF token.
*   **Rotation:** Each use of a refresh token revokes it and issues a new one. Reusing a revoked token revokes the user's whole session family, except within a 10-second grace window (`REFRESH_REUSE_GRACE_SECONDS`) that tolerates concurrent refreshes from one client.
*   **Revocation:** Redis-backed blacklist allows immediate revocation of access tokens when needed (logout, password change, anonymisation of a user under GDPR).

## 10. Encryption at Rest for Sensitive Settings

**Decision:** Sensitive configuration values (LLM API keys, SMTP passwords, the recipes module's Jina API key) are encrypted at rest using Fernet symmetric encryption (`app/services/crypto_service.py`).

**Rationale:**
*   **Key derivation:** Encryption key is derived from `ENCRYPTION_KEY` (falling back to `SECRET_KEY` when it is empty) using PBKDF2-HMAC-SHA256 with 600,000 iterations and the per-deployment `FERNET_SALT`. A key rotation keeps the old key in `PREVIOUS_ENCRYPTION_KEY` for reading while `manage.py secrets reencrypt` rewrites the stored values; the salt has no rotation path.
*   **Transparent prefix:** Encrypted values are prefixed with `enc:` for easy identification. The API returns masked values (`**********`) to the frontend.
*   **Merge-safe PUT:** Update endpoints preserve existing encrypted values when fields are not changed, preventing accidental plaintext storage.

## 11. Interceptors vs. EventBus — Two Extension Mechanisms

**Decision:** We provide two distinct extension mechanisms with different semantics: synchronous Interceptors and asynchronous EventBus.

| | Interceptors | EventBus |
|---|---|---|
| **Execution** | Synchronous, in-request | Asynchronous, post-response |
| **Can mutate data** | Yes | No |
| **Can block operations** | Yes (raise error) | No |
| **Ordering** | Priority-based pipeline | Consumer Group ordering |
| **Persistence** | In-process | Redis Streams |
| **Use case** | Validation, enrichment, policy | Side effects, notifications, audit |

**Rationale:**
*   **Clear separation of concerns:** Validation and data mutation must happen before the database write (interceptors). Side effects like notifications, webhook delivery, and cache invalidation should not block the request (event bus).
*   **Fault isolation:** A failing event handler does not block the user's request. A failing interceptor correctly aborts the operation.

## 12. `context_tag` over `category_type` (Domain Neutrality)

**Decision:** `context_tag` is the category's owner label — a neutral, extensible string that does not bake domain semantics into the core schema. `category_type`, the food profile's old FREEZER / FRIDGE / PANTRY column, was dropped before the first release, before the chain was flattened into the v0.11.0 baseline.

**Rationale:**
*   **Scalability:** `category_type` used food-specific values (`FREEZER`, `FRIDGE`, `PANTRY`). A new vertical (equipment, library) would require adding values to a core enum — violating the neutrality principle.
*   **Convention over configuration:** `context_tag` is a plain string (e.g., `'equipment'`, `'food'`, `'cold_storage'`). Modules define their own tags without modifying core code.
*   **No legacy column:** `category_type` needed a deprecation cycle once published, so it left before the release rather than staying as a second source beside `context_tag` and `group_label`.

## 13. `meta_data` Namespace Convention

**Decision:** Modules must namespace their keys within the shared `meta_data` JSONB column on Core models (e.g., `meta_data['nutrition']`, `meta_data['equipment']`). Flat keys are forbidden.

**Rationale:**
*   **Collision prevention:** Multiple modules writing to the same `meta_data` column could overwrite each other's data. Namespacing (`meta_data['equipment']['serial_number']` vs `meta_data['nutrition']['calories']`) prevents this.
*   **Discoverability:** Namespaced data makes it trivial to identify which module owns which data.
*   **Clean removal:** When a module is disabled, its namespaced data can be cleaned up without affecting other modules.

## 14. PgBouncer Transaction-Mode Connection Pooling

**Decision:** We use PgBouncer in transaction-mode pooling between the application and the main PostgreSQL database in production — development connects directly — (a second pooler for the products database was removed: nothing connected through it).

**Configuration:** The application uses `pool_size=20 + max_overflow=10` for the sync engine and `pool_size=10 + max_overflow=10` for the async engine per worker; since [ADR-006](adr/ADR-006-async-only-service-functions.md) requests run on the async engine, and the sync one serves tooling (migrations, `shell.py`, the `manage` commands). In production, PgBouncer (`pgbouncer-main`) uses `DEFAULT_POOL_SIZE=30` for the main database; the optional products database is reached directly, without a pooler.

**Rationale:**
*   **Connection efficiency:** FastAPI with multiple Uvicorn workers can open hundreds of idle connections. PgBouncer multiplexes them into a small fixed pool, reducing PostgreSQL memory usage.
*   **Separate databases:** The products database has a separate SQLAlchemy connection pool, so its queries do not consume connections from the main database's application pool.
*   **Production-ready:** Transaction-mode pooling works with SQLAlchemy's session management, with two application-level accommodations: the asyncpg engine runs with `prepared_statement_cache_size=0` (`app/database.py`), because a prepared statement does not survive the pooler handing the client another server connection, and the session-level advisory lock taken during migrations bypasses the pooler (`docs/SCALING.md`).

## 15. Equipment Module as Proof of Module Architecture

**Decision:** The Equipment module (`app/modules/equipment/`) demonstrates the full capability of the module system without modifying core models. It implements IT Asset Management (ITAM) as a self-contained vertical.

**Features implemented entirely within the module:**
*   Checkout/checkin assignments with person tracking
*   Maintenance log CRUD
*   Warranty alerts with configurable day threshold
*   Handover protocol generation (HTML + PDF) with customizable templates
*   Audit campaigns with email-based attestation
*   Bulk import (CSV/XLSX) with column mapping
*   Custom equipment dashboard with status breakdown
*   "Retire" as an equipment status (`equipment_status = 'RETIRED'`), not a deletion

**Rationale:**
*   **Proves the architecture:** A complex vertical (ITAM) was built entirely as a module without adding domain columns to Core models. Equipment-specific data lives in `meta_data['equipment']` and module-local tables.
*   **Template for new verticals:** Future modules (library, fleet management, lab equipment) can follow the same pattern.

## 16. Frontend Technology Stack

**Decision:** React 18 with TypeScript, Vite as the build tool, TailwindCSS for styling, Zustand for client state, TanStack React Query for server state, and i18next for internationalization.

**Rationale:**
*   **Type safety:** TypeScript with a strict "No-Any" policy ensures compile-time safety across the frontend.
*   **Server state separation:** TanStack React Query handles caching, invalidation, and optimistic updates, keeping components stateless. All mutations are extracted to dedicated hooks in `modules/<module>/hooks/`.
*   **Design system consistency:** TailwindCSS with design tokens and a `src/components/ui/` library (Button, Card, Input, Badge, etc.) ensures visual consistency. ESLint refuses a raw `<h1>`, `<button>`, `<input>` or `<select>` in a module page; the components in `src/components/ui/` take their place.
*   **Modular frontend:** Each frontend module is a `src/modules/<name>/` directory with a `module.ts`, adding `pages/`, `components/`, `hooks/` and `api/` where it needs them. Most mirror a backend module of the same name; six (`announcements`, `inventory`, `launcher`, `partners`, `settings`, `spaces`) do not. Cross-module imports are minimized.
*   **No service worker:** the build ships none — `vite-plugin-pwa` was removed, so there is no offline cache and no installability. `src/main.tsx` keeps its unregister block so an installation that caught a worker from an earlier build drops it on the next visit; nothing replaces a worker nobody registers again.

## 17. One Document Date

**Decision:** A document has one date the module files it under: the date it is *for* (`scheduled_date`, falling back to the day it was created when none is stated). The register, the period guard, the cost layers, the number's year and month, and the plain documents list — its date-range filter and its "newest first" order — all read that one date. The moment of entry (`created_at`) stays on the row for the audit trail and only breaks ties.

**Rationale:**
*   **Two dates were two answers.** The register and the period guard read the document date while the list read the moment of entry, so one date range asked of the list and of the register named two different sets of documents — a disagreement an auditor comparing the two could not explain.
*   **The date the document is about is the accounting date.** A delivery entered on 2 January and dated to 31 December belongs to December in every ledger it touches; the list is the page people open first, and it has to agree with the pages that close the books.
*   **Entry time is audit, not filing.** When something was typed in is a question for the audit trail, which records it; it is not a dimension worth a second filter in the interface, and naming the difference there would only re-introduce the two answers.


## 18. Decimal on the Wire

**Decision:** A stock quantity or an amount of money crosses the API as a string — Pydantic's default for `Decimal` — never as a JSON number. No response schema carries an explicit `Decimal -> float` serializer, and a test pins the shape (`isinstance(value, str)`) on the item, archive, stock-quant, purchase-order and receipt endpoints, so a serializer that returns turns the gate red rather than passing a value comparison that cannot tell `"12.5"` from `12.5`.

**Outside the contract, on purpose:** fields that are not a stock quantity or an amount of money stay `float`. That is: a product's unit weight and volume (`weight_value`, `volume_value` — a physical measure of one piece), the reorder threshold (`min_quantity`), the analytics figures of the stats module (estimates rounded for reading, computed in Decimal and quantised before they leave), the picking suggestions of the recipes module (`opened_quantity`, candidate `quantity` — hints for a cook, never written back to stock) and a recipe's cost estimate (`IngredientCost.estimated_cost` — an estimate labelled as such). Request bodies are not part of this rule either: Pydantic accepts a string into a `float` field, so `LabelAssignRequest.quantity` stays as it is.

**Rationale:**
*   **A float cannot carry what a Decimal column holds.** `Numeric(12,3)` has values a double cannot represent; the reader of a JSON number has no way to tell a value that was exact from one that was rounded for transport.
*   **One type, one shape.** Half the API already sent strings; a client that had to check which endpoint it was talking to before parsing a quantity was a bug waiting for the next endpoint.
*   **The line is drawn by meaning, not by column type.** What gets added to stock or to an invoice is exact; what describes a product or estimates a cost for reading is not, and forcing every number into a string would make the contract harder to read without making any figure more correct.


## 19. Every Day and Month a Report Cuts Is the Organization's

**Decision:** Anything that decides *which day it is* or *which month a figure belongs to* reads the organization's clock — `core_api.organizations.today_async`, `.timezone_async`, `.window_start_async` — never the server's `date.today()`. That covers the core read-models, the equipment warranty and maintenance alerts, the depreciation reference date, the maker module's monthly result (a run's number takes its year from the document numbering register, which reads it in UTC). `compute_book_value` takes `as_of` as a required argument for the same reason: a default of "today" is a default of "the server's today", and nothing on the screen says so.

Timestamps written to the row (`created_at`, `completed_at`, `checked_in_at`) stay UTC instants. The clock decides how an instant is *read*, not how it is stored.

**Rationale:**
*   **The boundary is where the reader stands.** An organization in Auckland closing its month saw the month end at 11am on the last day it was still open there; a run completed at one in the morning on the local first landed in the previous month's chart.
*   **Two callers of one helper must agree.** The fleet valuation loops over every asset. Reading `date.today()` per asset let a loop that crossed midnight depreciate two assets in one figure as at two different days — a difference no one could see and no one could reproduce.
*   **A silent fallback outlives the fix.** The pass that moved the core reports onto the organization's clock left three module paths on the server's, because the helper they called still had a "today" of its own to fall back on. Requiring `as_of` is what makes the next such path fail loudly instead of quietly.


## 20. A Released Migration Is Edited Only When the Edit Is a No-Op on Migrated Databases

**Decision:** A migration that has already been released may be edited in place only when, on every database that has already replayed it, the edit is operationally a no-op — for example a `create_table` that sits behind an `_table_exists` guard, or a change to a branch the chain never takes again. An edit that changes what the migration *does* on databases that already ran it is refused: the fix is a new migration on top. Every in-place edit of a released file names, in its commit or pull request, the guard that makes it a no-op for existing databases.

**Rationale:**
*   **The chain is shared history.** Every deployment replays the same files; changing what a step did silently splits the fleet into databases that ran the old step and databases that will run the new one, with no record of the difference.
*   **The narrow window is real.** A precision guard once needed a table to exist for fresh databases migrated by the core chain alone; the edit was operationally a no-op on every database that had already passed the guarded step, and the reviewer verified exactly that. Naming the window — no-op on migrated databases, or a new migration — beats an unwritten rule that each case re-litigates.
*   **The burden of proof belongs to the editor.** "It seemed harmless" is not a guard. The commit that edits a released file is the one place a reader will look; if the no-op argument cannot be written there in one sentence, the edit is not in the window.
