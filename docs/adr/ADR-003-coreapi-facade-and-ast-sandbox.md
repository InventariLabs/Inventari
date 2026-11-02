# ADR-003: CoreAPI Facade + AST Architecture Lint

## Status

Accepted — 2026-07-12

## Context

Inventari's defining architectural property is its **modular plugin system**: a
domain-neutral Core serves food tracking, IT asset management, warehouse
operations, pharma, and future verticals equally. Modules (`app/modules/*`) add
vertical-specific behavior without modifying Core. For this to work at scale,
there must be a **single, enforced boundary** between Core's data layer and its
consumers. Without one, modules inevitably reach into `app.models` and
`app.services` directly, and within months the "modular" architecture collapses
into a coupled monolith — the fate of most plugin systems.

The specific forces at play:

1. **Cross-cutting concerns must always fire.** Every Core write must trigger
   the Interceptor pipeline (authorization, validation rules such as "cannot
   delete an assigned asset") and the EventBus (34 system events then — today: 28 — for audit,
   webhooks, notifications, stats). Direct `db.add(Model(...))` bypasses both,
   producing silent data corruption (no audit trail, no webhook, violated
   invariants).
2. **Multi-tenancy must always hold.** Every query must scope to
   `organization_id`. Scattered raw queries inevitably forget.
3. **Contributors cannot be trusted to read the rules.** A `CONTRIBUTING.md`
   that says "don't import app.models in your router" will be violated on day
   one. The boundary must be **enforced in CI**, not documented in prose.
4. **DX must remain good.** If the boundary is a review-board or runtime check,
   contributors hit it late and get frustrated. It must be fast, local, and
   point at the exact offending line.

## Decision

**A single `CoreAPI` facade is the only legal way for modules (and API routers)
to read or write Core data, enforced by an AST-based architecture linter that
runs in CI.**

### The facade

`backend/app/core/public_api/__init__.py` defines `class CoreAPI` — a facade
holding 28 sub-namespaces at the time (33 on 2026-10-31; `items`, `stock`, `valuation`, `product_templates`,
`locations`, ...). A single module-level instance `core_api = CoreAPI()` is the
import target:

```python
from app.core.public_api import core_api

result = await core_api.items.create_async(db, org_id, data, user)
rate  = await core_api.valuation.get_current_rate_async(db, org_id, template_id)
```

**Transaction contract** (documented in the class docstring): every write method
calls `db.flush()` and **never `db.commit()`**. The caller (router/handler)
controls the transaction boundary. This is what lets the maker/production flow
consume inputs, create output, record valuation, and write audit moves as one
atomic unit — or roll the whole thing back on any error.

### The AST linter

`backend/app/core/architecture_lint/` parses every Python source file with the
stdlib `ast` module and enforces four boundary rules (further checks — tenancy,
events, migrations, contracts and others — have since joined them in the same
package):

| Rule | Scope | Forbidden | Severity |
|------|-------|-----------|----------|
| Public API abstraction | `public_api/**` (except `__init__.py`) | `import app.models` / `app.database` | `::error` (exit 1) |
| API-layer import guard | `app/api/**` | `from app.models`, `from app.database` | `::error` (new) / `::notice` (baselined) |
| Module boundary guard | `app/modules/**` (except `models.py`, tests) | `app.models`, `app.database`, `app.services` | `::error` |
| API-layer CQRS write guard | `app/api/**` | `db.add(`, `db.delete(`, `db.merge(` (and `session.*`) | `::error` |

`if TYPE_CHECKING:` imports are exempt (needed for type hints only). Existing
violations are tracked in a baseline; new ones fail CI immediately.

**Enforcement:** the lint runs locally, through the pre-commit hook, on
every commit that stages Python, and as part of `make lint`; in CI, `.github/workflows/ci.yml` runs
`uv run python manage.py arch lint` on pushes and pull requests to `dev`
and `main` and on manual `workflow_dispatch`. A failure exits 1 and blocks the job.

### Alternatives considered

| Approach | DX | Enforcement | Verdict |
|----------|----|-------------|---------|
| **Runtime guards** (check import stack at startup) | Late, vague errors | Strong | Rejected — errors surface only at boot/test time, far from the line that caused them. |
| **Review board** (humans check in PR) | Good | Weak (human error) | Rejected — does not scale; the first busy week lets violations through. |
| **AST lint (chosen)** | Fast, local, exact line | Strong (CI gate) | **Chosen.** Catches violations at `ruff`-like speed, points at the offending import. |
| **Full type-system boundary** (mypy plugin / protocol-only) | Slow, complex | Strong | Rejected — disproportionate effort; AST covers 95% of cases. |

### Why a facade over direct service calls

The facade centralizes the contract. A module calling `core_api.items.create_async`
gets multi-tenancy, interceptors, EventBus, and the flush-but-don't-commit
guarantee for free. A module calling `app.services.items.create_item_async`
directly gets the same logic *today*, but nothing prevents Core from refactoring
the service layer tomorrow. The facade is the **stable public surface**;
services are the private implementation. This is the same reason frameworks
expose `X.api` rather than `X.internal.services`.

## Consequences

### Positive

- **The boundary holds.** New contributors hit the lint error immediately, read
  the message ("Must use core_api"), and learn the pattern. The architecture
  cannot silently rot.
- **Cross-cutting concerns are non-optional.** Interceptors and EventBus fire on
  every Core write because there is no other path.
- **Stable module API.** Core can refactor its service internals without
  breaking modules, as long as `core_api` method signatures stay
  backward-compatible (additive changes only — see "Cross-Module API Contracts"
  in `backend/AGENTS.md`).
- **Fast feedback.** AST lint runs in milliseconds, locally runnable via
  `make lint-architecture`.

### Negative

- **Escape-hatch ceremony.** Legitimate read-only analytics (GROUP BY, window
  functions) that CoreAPI cannot express require the escape-hatch marker
  (`# architecture: allow_direct_db_access` + `# reason: ≥5 words`). See
  [ADR-010](ADR-010-escape-hatch-marker.md). This is correct but raises the
  entry barrier.
- **Facade can grow large.** 28 sub-namespaces then, 33 on 2026-10-31. Mitigation: mixins per
  namespace (`_items_reads.py`, `_items_writes.py`, `_items_stock_ops.py`, ...)
  keep each file focused.
- **Baselined legacy violations.** Pre-migration code has some baselined
  `app.models` imports in `app/api/**` (emitted as `::notice`, not errors). The
  baseline can only shrink, never grow.

### Risks

- **Facade becomes a dumping ground.** If every new Core operation is added to
  `core_api` without namespace discipline, it turns into a god-object.
  Mitigation: mandatory sub-namespaces; code review gate.
- **AST lint gives false sense of security.** It checks *imports*, not *correct
  usage*. A module can still misuse `core_api` (wrong org_id, missing flush).
  Mitigation: integration tests; the lint is necessary but not sufficient.

## Implementation

- Facade: `backend/app/core/public_api/__init__.py` (`class CoreAPI`, `core_api`
  `core_api` singleton at the end of the file).
- Per-namespace mixins: `backend/app/core/public_api/items.py`,
  `_items_reads.py`, `_items_writes.py`, `_items_stock_ops.py`,
  `_items_lifecycle.py` (removed since), `stock.py`, `valuation.py`,
  `stock_moves.py`, ...
- Linter source: `backend/app/core/architecture_lint/_violations.py`,
  `_constants.py`, `_main.py`.
- CI gate: `.github/workflows/ci.yml` — "Architecture lint" step.
- Local run: `make lint-architecture` (wraps `manage.py arch lint`).

## References

- `backend/AGENTS.md` §3 "Modular Architecture & DB Access (Friction-Driven Development)"
- `backend/AGENTS.md` §Backend.1 "Import Conventions" (the canonical `router.py` import block)
- [ADR-010](ADR-010-escape-hatch-marker.md) — the escape hatch for read-only analytics
- [ADR-007](ADR-007-interceptors-and-eventbus.md) — the cross-cutting mechanisms the facade triggers
- [ADR-004](ADR-004-stockquant-source-of-truth.md) — a CoreAPI invariant of the time (StockQuant sync),
  superseded by [ADR-022](ADR-022-one-number-of-stock.md)
