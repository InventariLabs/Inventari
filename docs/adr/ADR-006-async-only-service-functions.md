# ADR-006: Async-Only Service Functions (No Sync/Async Twins)

## Status

Accepted — 2026-06-22. Supersedes [ADR-005](ADR-005-sync-sqlalchemy-threadpool.md): the request path
runs on an `AsyncSession` over `asyncpg`.

## Context

Historically, Inventari maintained **parallel sync and async versions** of
every service function — e.g., `create_item()` (sync) and
`create_item_async()` (async). This duplication arose because some callers
were sync (CLI scripts, management commands, shell) and others were async
(FastAPI routes, event handlers).

By June 2026, the cost of this duplication became unsustainable:

- **~57 duplicated function pairs** across the codebase ("sync/async twins").
- **Maintenance tax.** Every bug fix, feature, or signature change had to be
  applied twice. Drift between the two variants caused subtle bugs (the sync
  version missed a validation the async version had, or vice versa).
- **Ambiguity.** Callers had to decide which variant to use, and sometimes
  mixed them incorrectly (calling the sync variant from an async context,
  blocking the event loop).
- **The `asyncio.run()` escape hatch existed.** Sync callers could already
  call async functions via `asyncio.run()` or `asyncio.to_thread()`, making
  the sync twin redundant.

The cleanup was executed in phases: rewriting test-only sync callers to
async, deleting dead sync functions in batches, and completing the
dual-session elimination (all 29 functions async-only), culminating in zero
twins (June 2026).

## Decision

**New service functions MUST be async-only (`async def`).** No sync/async
twins. If a sync caller needs access to an async service, it uses
`asyncio.run()` or calls the async function directly within an event loop.

### The rule (from `backend/AGENTS.md`)

> New service functions MUST be async-only. If a sync caller needs access,
> use `asyncio.run()` wrapper or call the async variant directly. Do NOT
> create parallel sync/async file variants (`foo_sync.py` + `foo_async.py`)
> or duplicate sync/async function pairs in the same file.
>
> **Exceptions:** CLI commands (`app/cli/`) and bulk import
> (`app/modules/nutrition/import_parquet.py`) may remain sync — this is architecturally
> correct.

### Enforcement

The architecture linter (`app/core/architecture_lint/`) emits a `::notice`
when sync/async file pairs are detected (e.g., `service_sync.py` alongside
`service_async.py`). This is informational, not blocking, but surfaces the
anti-pattern in PR review. Function-level twins (`foo` and `foo_async` in one
module) are checked by `_quality_checks_twins.py`: a new pair is an `::error`,
a pair listed in `app/core/sync_async_twin_baseline.txt` a `::notice`.

### Exceptions (architecturally correct sync)

| Path | Why sync is OK |
|------|----------------|
| `app/cli/` | CLI commands run in a sync context; wrapping everything in `asyncio.run()` adds ceremony with no benefit. |
| `app/modules/nutrition/import_parquet.py` | Bulk offline import, not request-served. Sync is simpler for batch processing. |

These are **not** violations — they are intentionally sync. The linter does
not flag them because neither holds a sync/async pair; it keeps no exclusion
list for them.

## Consequences

### Positive

- **Single source of truth.** One function per operation. Bug fixes and
  features apply once. Zero drift risk between variants.
- **Clear calling convention.** All services are `async def`. Callers know
  what to expect. No decision paralysis ("which variant do I call?").
- **Reduced codebase size.** 57 duplicate functions deleted (~1500+ lines
  removed during the cleanup).
- **The driver followed.** The async-only services made the move to a native
  async driver (asyncpg, `init_async_engine`) a change of engine rather than of
  every call site — the migration ADR-005 listed under "Scaling wall" as the
  cost of a future hosted tier.

### Negative

- **Sync callers need bridges.** CLI scripts and test helpers that call
  services must use `asyncio.run()` or `asyncio.to_thread()`; `shell.py`
  keeps the sync engine (ADR-005) and needs none. This is a
  small friction cost (~53 bridge sites in the codebase).
- **Testing complexity.** Sync test helpers that call services must be async
  tests (`pytest-asyncio`). Most tests are already async, but a few legacy
  sync test helpers required rewriting.

### Risks

- **"Why is this async?" confusion.** A new contributor seeing `async def`
  on a function that does no I/O might think it's unnecessary. The answer:
  uniformity — all services are async for consistency, even CPU-bound ones.
- **Bridge bugs.** `asyncio.run()` creates a new event loop per call, which
  can conflict with an existing loop (e.g., in tests). Mitigation: use
  `asyncio.to_thread()` when inside an existing loop, `asyncio.run()` for
  top-level sync entry points (CLI).

## Implementation

- **Cleanup complete:** June 2026 ("zero twins achieved"). Since 2026-08
  `app/core/sync_async_twin_baseline.txt` keeps twelve reviewed pairs
  (blocking-I/O offloads, `Session | AsyncSession` helpers, lifecycle hooks);
  a new pair fails the lint.
- **Lint rule:** `app/core/architecture_lint/_quality_checks_size.py`
  (`_check_sync_async_file_pairs`) detects sync/async file pairs and emits
  `::notice`; `_quality_checks_twins.py` checks function pairs.
- **CI gate:** The sync/async twin detection runs in the architecture linter
  CI step (`ci.yml`).

## References

- `backend/AGENTS.md` — "⚡ Sync/Async Rule" section
- The cleanup was done in three steps: completing the dual-session
  elimination, deleting the dead sync functions, and removing the sync
  `ModuleScopedSession` — zero twins achieved, 57 duplicates removed total.
- ADR-005 (sync SQLAlchemy driver — the original *driver* choice, superseded by
  this ADR, which also establishes the *service signature* rule)
- `docs/TECHNICAL_DECISIONS.md` §2
