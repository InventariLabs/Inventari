# ADR-005: Sync SQLAlchemy 2.0 with FastAPI ThreadPool (not asyncpg)

## Status

Superseded by [ADR-006](ADR-006-async-only-service-functions.md) — the request path no longer
uses a synchronous `Session` over `psycopg2`. Routes and services take an
`AsyncSession` over `asyncpg` (`init_async_engine` in `backend/app/database.py`).
A synchronous engine remains for tooling that has no event loop
(migrations, `shell.py`, the `manage` CLI commands and the test fixtures), and for
the products database, which the barcode scan provider reads from a worker thread
(`asyncio.to_thread` in `backend/app/modules/nutrition/scan_provider.py`). What
follows is the decision as it stood on 2026-06-22; the threadpool, the
sync-session rule and the bridge count it describes are history.

Accepted — 2026-06-22

## Context

Every new backend developer's first question: **"Why not async SQLAlchemy with
asyncpg? This is a FastAPI project."** FastAPI is marketed as an async
framework, so the expectation is an all-async stack. Inventari deliberately
uses the **synchronous** SQLAlchemy driver (`psycopg2`) inside `async def`
routes, relying on FastAPI's threadpool to handle concurrency. This decision
permeates the entire backend and must not be relitigated casually.

The system is a complex logistics engine with deep object graphs:
`item.category.name`, `item.storage_location.organization`, nested
relationships everywhere. Lazy loading is used extensively in services,
shell inspection, and template rendering.

## Decision

**Synchronous SQLAlchemy 2.0 (`psycopg2`) with FastAPI's default threadpool
(40 threads), fronted by PgBouncer in transaction-mode pooling.**

- Routes are declared `async def` (FastAPI does not run sync DB work in the
  event loop — it dispatches to a threadpool automatically).
- SQLAlchemy sessions use the sync `Session`, not `AsyncSession`.
- PgBouncer multiplexes the threadpool connections down to a small fixed pool
  (default 20 PostgreSQL connections).

> **Note (June 2026):** After the sync/async twin elimination (see ADR-006),
> service functions are **async-only** (`async def` signatures). They receive
> an `AsyncSession` and use SQLAlchemy's async ORM. This ADR describes the
> _driver_ choice (why not asyncpg from the start); ADR-006 describes the
> _service signature_ rule (why no sync/async duplication). The project
> evolved from pure sync → async services on top of the sync driver.

### Alternatives considered

| Approach                                             | Lazy loading                                                                                          | DX (shell)                                                                  | Concurrency ceiling       | Verdict                                                                                             |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| **async SQLAlchemy + asyncpg**                       | **Broken** — `await` required for every relationship access; `item.category` raises `MissingGreenlet` | Poor — shell inspection needs event-loop juggling                           | High (async-native)       | Rejected. Lazy-loading breakage across a deep object graph is a productivity killer and bug source. |
| **sync SQLAlchemy + psycopg2 + threadpool** (chosen) | **Works** — transparent relationship access, no `await` needed                                        | Excellent — `shell.py` (Shell Plus) works like Django's, instant inspection | Medium (threadpool-bound) | **Chosen.** DX and correctness win; PgBouncer offsets connection cost.                              |
| **Gevent/eventlet monkey-patching**                  | Works (green threads)                                                                                 | Medium                                                                      | Medium                    | Rejected. Monkey-patching is fragile, conflicts with async libraries, debugging nightmares.         |

### Why not async SQLAlchemy?

SQLAlchemy's async mode (`AsyncSession`) disables transparent lazy loading:
accessing a relationship attribute outside an awaited context raises
`MissingGreenlet`. In a logistics engine where services routinely traverse
`item.template.category.name` or `document.lines.product`, forcing explicit
`selectinload`/`joinedload` on every query path would:

1. **Massively increase boilerplate** — every read path must declare its
   eager-loading strategy upfront.
2. **Create latent `MissingGreenlet` bugs** — a developer adds a new
   relationship access, forgets to update the query's loading options, and
   gets a runtime crash only when that code path executes.
3. **Break the interactive shell** — `shell.py` (used for debugging, data
   inspection, one-off fixes) cannot easily manage async sessions.

The sync driver with FastAPI's threadpool gives the best of both: async HTTP
handling (FastAPI's event loop handles request I/O), sync ORM (transparent
lazy loading), and acceptable concurrency (threadpool + PgBouncer).

## Consequences

### Positive

- **Developer experience.** Transparent lazy loading across deep object
  graphs. `shell.py` enables Django-like instant data inspection without
  event-loop ceremony.
- **Productivity.** Services are simpler — no explicit eager-load declarations
  on every query, no `MissingGreenlet` debugging.
- **Performance parity.** For standard RDBMS workloads, sync psycopg2 with a
  well-configured connection pool (PgBouncer transaction-mode) matches or
  outperforms asyncpg due to lower per-operation overhead. Asyncpg shines for
  high-concurrency I/O-bound workloads, not for CPU-bound logistics logic.

### Negative

- **Threadpool ceiling.** FastAPI's default threadpool (40 threads) is a hard
  concurrency cap. Under heavy load, requests queue waiting for a thread.
  This is acceptable for self-hosted deployments but becomes a scaling factor
  for a hosted SaaS tier.
- **No true async DB I/O.** Long-running queries occupy a thread for their
  full duration. A slow analytics query blocks one of 40 threads.
- **Bridge complexity.** Async services calling sync helpers (or vice versa)
  require `run_in_threadpool` / `asyncio.to_thread` bridges. The codebase has
  ~53 such bridges — manageable but a recurring DX friction point.

### Risks

- **Scaling wall.** If a future hosted tier needs to handle
  hundreds of concurrent requests per instance, the threadpool ceiling
  becomes the bottleneck. **Mitigation:** plan an async read-path for hot
  endpoints (list, search, analytics) while keeping the sync write-path.
  Hybrid (sync-write + async-read) is viable without a full rewrite.
- **"Just switch to asyncpg" pressure.** Contributors will propose migrating
  to asyncpg. This ADR documents why that's not a quick win: the lazy-loading
  breakage affects hundreds of service paths. The migration cost is
  proportional to the size of the object graph, not the number of endpoints.

## Implementation

- **Driver:** `psycopg2` (sync) via SQLAlchemy 2.0 `create_engine`.
- **Session:** `Session` (sync ORM). Service functions are `async def` but
  operate on the sync session via the threadpool.
- **Pooling:** in production the main database is reached through PgBouncer in
  transaction mode (the `pgbouncer-main` service in `docker-compose.prod.yml`);
  development connects directly. The products database has its own, smaller
  SQLAlchemy pool (`products_engine` in `backend/app/database.py`), so
  food-module queries cannot starve the main pool. Pool sizes and the
  per-worker connection arithmetic are documented next to the engines in
  `backend/app/database.py`.
- **Shell:** `backend/shell.py` — Shell Plus with auto-imported models,
  works without async ceremony.

## References

- `docs/TECHNICAL_DECISIONS.md` §2 (original rationale)
- `backend/app/config.py` — database engine configuration
- PgBouncer config: the `pgbouncer-main` service in `docker-compose.prod.yml`
- ADR-006 (sync-only service rule — why no sync/async twins)
