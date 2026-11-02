# ADR-008: Multi-Layered Application-Layer Isolation (not DB Row-Level Security)

## Status

Accepted — 2026-06-22

## Context

Inventari is multi-tenant: a single database serves multiple organizations,
and isolation must guarantee that Organization A can never read or modify
Organization B's data. Security auditors and infrastructure engineers will
ask: **"Why not use PostgreSQL Row-Level Security (RLS)? It's the
database-native solution."**

The choice is between:

1. **DB-native RLS** — PostgreSQL policies that automatically filter rows by
   tenant at the query level.
2. **Application-layer isolation** — the application enforces tenant scoping
   in code, with multiple independent guardrail layers.

This ADR documents why Inventari chose application-layer isolation with
defense-in-depth, and what trade-offs that entails.

## Decision

**Multi-layered application-layer isolation** with seven independent
guardrail layers. No PostgreSQL Row-Level Security.

### The seven layers

| #   | Layer                                  | Mechanism                                                                                                                       | Location                                      |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| 1   | **AST import guard**                   | `app/core/architecture_lint/` blocks forbidden imports (`app.models`, `app.database`, `app.services`) in module code                            | Static analysis (CI)                          |
| 2   | **Escape-hatch validation**            | Direct DB access requires `# architecture: allow_direct_db_access` marker + reason (≥5 words)                                   | Static analysis (CI)                          |
| 3   | **CQRS enforcement**                   | Read-only escape-hatch files cannot call `db.commit()`, `db.add()`, `db.delete()` on Core tables                                | Static analysis (CI)                          |
| 4   | **API-layer write prohibition**        | Router files cannot perform direct DB writes to Core tables                                                                     | Static analysis (CI)                          |
| 5   | **Public API model guard**             | `CoreAPI` public endpoints block raw model imports                                                                              | Runtime + static                              |
| 6   | **AsyncModuleScopedSession**           | Runtime session proxy auto-filters by `organization_id` and validates tenant ownership on CRUD                                  | Runtime — **background jobs only**, see below |
| 7   | **Tenant carried into every endpoint** | An endpoint touching the DB must use `require_org()` / `organization_id` / the user context; new ones that do not fail the lint | Runtime + static analysis (CI)                |

### Where each layer runs (as of 2026-09-12)

The seven layers do not all stand in the same place: they differ in which
of them sits between a request and another tenant's rows.

- **Layers 1–5 are static analysis** and they hold: every one of their
  baselines is empty, so nothing is grandfathered and a new violation
  fails CI. What they guarantee is a _shape_ — a module cannot import
  Core models, cannot write through the escape hatch, cannot leak a model
  out of `CoreAPI`. None of them filters a row.
- **Layer 6 does filter, and it is not in the request path.**
  `AsyncModuleScopedSession` is the only layer that injects an
  `organization_id` filter by itself. It has three call sites, all in
  background jobs (`purchase_orders`, `webhooks`), reached through
  `ModuleContext.tenant_session`. Request handlers receive a plain
  `AsyncSession`. Its filtering has a documented limit:
  entities, aliases and org-exposing subqueries are filtered, **an
  explicit join passes through untouched**. Putting it in the request
  path would mean changing the session type carried into `core_api` and
  the services — about 470 of the 540 route handlers reach the session through
  `get_current_user_context` — in exchange for a filter that does not
  cover explicit joins. That trade-off has not been taken.
- **Layer 7 guards the request path.** It is enforced as a lint check
  (added 2026-09-12) — an endpoint that takes a
  database session must _use_ something carrying the tenant, and the
  endpoints that are global by design are listed in
  `app/core/request_scope_baseline.txt` (22 of them: superuser views,
  pre-login flows, the public attestation pages). The check verifies that
  the endpoint _has_ the tenant to pass on, not that the query it
  delegates to ends up filtered; that still lives in the service, and in
  layer 6 where the session is scoped.

So the count in the request path is: five static layers shaping
what code may do, and one runtime layer making sure the
tenant reaches the work. Tenancy tests are the backstop.

### Alternatives considered

| Approach                                  | Isolation guarantee                                                                                | Debuggability                                                                      | Migration complexity                                                   | Verdict                                                                                                |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **PostgreSQL RLS**                        | Strong (DB-enforced)                                                                               | Poor (policies are opaque; debugging "why is this row hidden?" requires `EXPLAIN`) | High (every table needs policy; schema changes require policy updates) | Rejected. Debugging and migration overhead outweigh the guarantee.                                     |
| **Schema-per-tenant**                     | Strongest (physical isolation)                                                                     | Good                                                                               | Very high (migration per tenant, cross-tenant queries impossible)      | Rejected. Too heavy for the shared-DB model; revisit only if a deployment requires physical isolation. |
| **App-layer + defense-in-depth** (chosen) | Depends on scoped queries and complementary checks; the session proxy is background-only | Excellent (each layer is visible, testable, debuggable)                            | Low (add new layers independently)                                     | **Chosen.**                                                                                            |

### Why not PostgreSQL RLS?

1. **Debugging opacity.** When a row is unexpectedly hidden or visible, RLS
   policies are hard to inspect. `EXPLAIN` doesn't always reveal which policy
   fired. In app-layer isolation, every filter is a visible `.where()`
   clause in the query — trivially debuggable.
2. **Migration complexity.** Every new table needs an RLS policy. Every schema
   change (new column, renamed table) requires updating policies. With 14+
   modules adding tables, the policy maintenance burden is high.
3. **RLS has its own bypasses.** A superuser connection or migration script
   can bypass RLS. The application layers reduce different risks, but they do
   not guarantee that one catches every miss in another: request sessions are
   unscoped, and `require_org()` returns the organization ID without filtering
   queries. Services must apply that ID, and tenancy tests check the result.
4. **Simple SQL.** Application-layer isolation keeps SQL readable:
   `SELECT ... WHERE organization_id = :org_id`. RLS rewrites queries
   invisibly, making the executed SQL differ from the written SQL.

### Why not schema-per-tenant?

Physical isolation (separate schema or database per org) is the strongest
model but:

- **Cross-tenant queries are impossible** (platform-level analytics,
  superadmin views, marketplace billing).
- **Migration per tenant** — each schema must be migrated independently.
- **Connection pool fragmentation** — each schema may need its own pool.

Reconsidered only if a future deployment model demands physical isolation;
currently deferred.

## Consequences

### Positive

- **Defense in depth.** Seven layers address different failure modes; five
  are static and the `AsyncModuleScopedSession` filter is outside the request
  path. They do not each catch every failure of the others: request services
  must scope their queries, with tenancy tests as a backstop.
- **CI enforcement.** Layers 1–5 are static analysis, enforced in CI. A PR
  that violates module boundaries or tenant scoping is blocked before merge.
- **Debuggable.** Every filter is visible SQL. Every guard is testable code.
- **No DB-level policy maintenance.** Migrations need no RLS policies; direct
  database access still has to enforce tenant isolation itself.

### Negative

- **Not DB-enforced.** If the layers that stand between a request and the
  rows are bypassed, the DB returns cross-tenant data. RLS would prevent
  this at the DB level. Mitigation: the layers are independent and tested.
  Note that fewer than seven of them stand in the request path (see "Where
  each layer runs").
- **Runtime overhead.** `AsyncModuleScopedSession` adds a proxy layer to queries
  made through it in background jobs; request queries use a plain session.
- **Discipline required, with a lint gate behind it.** A new endpoint that
  takes a database session and never touches the organization fails the
  architecture lint (`_check_request_scope`). What the gate cannot see is
  whether the service the endpoint delegates to actually filters; that
  remains code review and the tenancy tests.

### Risks

- **"Just enable RLS" pressure.** Security auditors may push for RLS as
  defense-in-depth on top of app-layer isolation. This is possible as an
  additional layer (not a replacement) if the operational complexity is
  justified by a compliance requirement (e.g., SOC 2, HIPAA).
- **New endpoint forgets the org scope.** A router that skips it returns
  cross-tenant data. Mitigation: the lint refuses an endpoint with no
  carrier at all; the canonical endpoint pattern (`backend/AGENTS.md` §Backend.2)
  and code review cover the case where the carrier is present and simply
  not used to filter.

### Revisit conditions (added 2026-07-25)

This decision is **revisited — not by default, but when any of the following
becomes true:**

1. **Direct DB access outside the application.** BI/analytics read replicas,
   data exports, or routine manual SQL operations on production data. RLS is
   the only layer that protects tenants when the consumer is not the
   application.
2. **Client-driven compliance requirement.** A customer or audit (SOC 2,
   ISO 27001, HIPAA, public procurement) explicitly requires DB-enforced
   tenant isolation.
3. **An actual isolation incident.** Any confirmed bypass of the app-layer
   guardrails in production triggers re-evaluation of RLS as an additional
   layer.

> **Update (2026-07-31, ADR-012):** the dormant GUC plumbing
> (`set_db_organization_context`, `DB_TENANT_CONTEXT_ENABLED`) was not
> wired to any call site and was removed as dead code. If RLS
> is ever introduced, the session plumbing must be re-added deliberately.

## Implementation

- **Static analysis:** `backend/app/core/architecture_lint/` — AST-based
  guards for imports, escape hatches, CQRS, write prohibition.
- **Runtime:** `backend/app/core/` — `AsyncModuleScopedSession`, CoreAPI model
  guard.
- **Endpoint pattern:** `backend/AGENTS.md` §Backend.2 "Canonical Endpoint Pattern" —
  `require_org()` helper (`backend/app/core/deps.py`), used by the canonical
  endpoint pattern.
- **CI:** `ci.yml` runs the architecture linter; PRs that violate isolation
  layers are blocked.

## References

- `docs/TECHNICAL_DECISIONS.md` §4 (original rationale + 7-layer table)
- `backend/app/core/architecture_lint/` — static analysis guards
- `backend/AGENTS.md` — Backend Engineering Standards (`require_org()` pattern)
- Schema-per-tenant isolation was considered and deferred.
