# Architecture Decision Records (ADR)

An ADR captures **why** a non-obvious architectural decision was made — the
context, alternatives considered, and consequences. New contributors read these
to understand the rules enforced by the architecture linter and `AGENTS.md`
without having to reverse-engineer them from code.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-migration-isolation.md) | Per-Module Migration Isolation via Separate Version Tables | Accepted |
| [ADR-002](ADR-002-agpl-v3-and-dual-licensing.md) | AGPL v3 License + Dual Licensing | Accepted |
| [ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md) | CoreAPI Facade + AST Architecture Lint | Accepted |
| [ADR-004](ADR-004-stockquant-source-of-truth.md) | StockQuant Source-of-Truth + `Item.quantity` Denormalized Cache | Superseded by ADR-022 |
| [ADR-005](ADR-005-sync-sqlalchemy-threadpool.md) | Sync SQLAlchemy 2.0 with FastAPI ThreadPool (not asyncpg) | Superseded by ADR-006 |
| [ADR-006](ADR-006-async-only-service-functions.md) | Async-Only Service Functions (No Sync/Async Twins) | Accepted |
| [ADR-007](ADR-007-interceptors-and-eventbus.md) | Two Extension Mechanisms — Interceptors (sync) and EventBus (async) | Accepted |
| [ADR-008](ADR-008-app-layer-isolation-not-rls.md) | Multi-Layered Application-Layer Isolation (not DB Row-Level Security) | Accepted |
| [ADR-009](ADR-009-core-neutrality-and-3-vertical-test.md) | Core Neutrality & the 3-Vertical Test | Accepted |
| [ADR-010](ADR-010-escape-hatch-marker.md) | Escape-Hatch Marker for Read-Only Core DB Access | Accepted |
| [ADR-011](ADR-011-core-neutrality-vocabulary.md) | Core Neutrality Vocabulary (USED/DISPOSED over CONSUMED/DISCARDED) | Accepted, amended |
| [ADR-012](ADR-012-rls-deferred-guc-removed.md) | RLS Deferred — Dead Tenant-GUC Code Removed | Accepted |
| [ADR-013](ADR-013-success-token-vs-profile-accent.md) | `success-*` Is a Separate Semantic Token; Profiles Repaint Only `primary-*`/`accent-*` | Accepted |
| [ADR-014](ADR-014-storage-hierarchy-fixed-levels.md) | Storage Hierarchy Has Three Fixed Levels | Superseded by ADR-018 |
| [ADR-015](ADR-015-unit-weight-on-product-template.md) | Unit Weight Belongs to the Product Template, Line Weight Is Computed | Accepted |
| [ADR-016](ADR-016-default-piece-unit.md) | A Product Without a Unit Is Counted in Pieces | Accepted, amended |
| [ADR-017](ADR-017-fiscal-features-are-country-packs.md) | Fiscal Features Are Country Packs, Not Core | Accepted, amended |
| [ADR-018](ADR-018-storage-hierarchy-unbounded-depth.md) | Storage Hierarchy Has Unbounded Depth | Accepted |
| [ADR-019](ADR-019-modules-are-certified-not-sandboxed.md) | Modules Are Certified, Not Sandboxed | Accepted |
| [ADR-020](ADR-020-cost-layers-lock-per-product-not-per-shelf.md) | Cost Layers Lock per Product, Not per Shelf | Accepted, superseded in part by ADR-022 |
| [ADR-021](ADR-021-handling-units-are-not-modelled.md) | Handling Units Are Not Modelled | Accepted, superseded in part by ADR-022 |
| [ADR-022](ADR-022-one-number-of-stock.md) | One Number of Stock — the Record Is the Stock, a Quant Is a Sum, the Anchor Is the Lock | Accepted |
| [ADR-023](ADR-023-retry-the-whole-request-when-the-database-aborts-it.md) | Retry the Whole Request When the Database Aborts It | Accepted |
| [ADR-024](ADR-024-recipe-import-fetches-through-the-reader-not-the-server.md) | Recipe Import Fetches Through the Reader, Not From the Server | Accepted |
| [ADR-025](ADR-025-completed-documents-do-not-store-their-pdf.md) | Completed Documents Do Not Store Their PDF | Accepted |

> **Numbering note:** from the first public release on, ADR IDs are
> permanent and never renumbered.
> If an ADR is superseded, its file stays in place with status `Superseded by
> ADR-XXX`.

## When to write an ADR

Write one when a decision is **non-obvious**, **hard to reverse**, or **governs
a rule that `AGENTS.md` or the architecture linter enforces**. If a future
contributor would ask "why does it work this way and not the obvious other
way?", it deserves an ADR.

## Format

```
# ADR-XXX: Title
## Status      — Accepted (date) [, amended (date) | , superseded in part by ADR-YYY]
                 | Superseded by ADR-YYY | Deprecated (date)
## Context     — forces, constraints, the problem
## Decision    — what we chose
### Alternatives considered — table of rejected options + why
## Consequences — positive, negative
## Risks       — and mitigations
## Implementation — concrete files / configs that realize the decision
## References  — AGENTS.md sections, related ADRs, prior art
```
