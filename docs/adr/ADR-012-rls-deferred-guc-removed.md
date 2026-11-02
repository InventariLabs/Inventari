# ADR-012: RLS Deferred — Dead Tenant-GUC Code Removed

## Status

Accepted (2026-07-31)

## Context

ADR-008 decided that tenant isolation lives at the application layer
(`organization_id` filtering + architecture lint), not in PostgreSQL
Row-Level Security. As a hedge, the codebase kept a partial RLS plumbing
layer:

- `settings.DB_TENANT_CONTEXT_ENABLED` (default `False`, never enabled in
  any environment, compose file, or docs),
- `set_db_organization_context()` / `clear_db_organization_context()` in
  `backend/app/database.py`, setting the `app.current_organization_id` GUC,
- **zero call sites** outside their own unit test — the functions were never
  invoked by session middleware, deps, or startup.

This was dead code with a maintenance cost: ADR-008 even described it as
"already sets the GUC on every connection", which was false and could have
led a future contributor to build RLS policies on plumbing that does not
run. Meanwhile the real tenancy boundary was hardened in the same period
(`organization_id` required across `public_api`, lint-enforced), making the
dormant alternative path purely confusing.

## Decision

Remove the dead RLS plumbing (config flag, both GUC helpers, their unit
test). Row-Level Security is **deferred until an enterprise requirement
appears** (the trigger conditions ADR-008 already lists: direct database access
outside the application, a client-driven compliance requirement, or a
confirmed app-layer isolation incident).

If RLS is ever introduced, the session plumbing must be re-added
deliberately — as a session-level middleware that sets
`app.current_organization_id` per transaction, plus per-table policies —
and ADR-008's trigger conditions must be revisited first.

### Alternatives considered

| Option | Rejected because |
|---|---|
| Keep the GUC helpers "just in case" | Dead code that misrepresents itself as working plumbing (ADR-008's stale claim); zero callers; two small helpers and a flag, cheap to write again when a requirement appears |
| Finish RLS now (policies + enable the GUC) | Doubles the tenancy-enforcement surface for zero current requirement; policy drift between app-layer filters and DB policies is a security risk in itself; no customer or regulation asks for it |

## Consequences

- Positive: one tenancy mechanism, enforced and lint-checked; no false
  sense of a second safety net; ADR-008's description corrected.
- Negative: reintroducing RLS later requires re-adding the plumbing (a few
  dozen lines) instead of flipping a flag — acceptable given the trigger
  conditions are rare and the old code survives in history.

## Implementation

- Removed: `DB_TENANT_CONTEXT_ENABLED` (`backend/app/config.py`),
  `set_db_organization_context` / `clear_db_organization_context`
  (`backend/app/database.py`),
  `backend/tests/unit/test_db_tenant_context.py` (removed since).
- The actual tenancy boundary after this ADR:
  `organization_id` required in `app/core/public_api/` signatures (ten older
  functions, which take the organization from the caller's context or serve
  global rows, are listed in `backend/app/core/public_api_missing_org_baseline.txt`),
  `require_org()` in endpoints, architecture-lint rules 17–18
  (optional-org ban, escape-hatch org filter).

## References

- [ADR-008](ADR-008-app-layer-isolation-not-rls.md) — the standing
  app-layer-isolation decision (this ADR removes its dormant hedge)
- `docs/subsystems/CONTRACTS_STABILITY.md`
