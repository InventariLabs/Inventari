# ADR-023: Retry the Whole Request When the Database Aborts It

## Status

Accepted — 2026-09-30

## Context

The architecture stands on READ COMMITTED and on keeping conflicts out
with locks rather than retrying through them (ADR-020 and its siblings).
That discipline is guarded — lock-order tests, a TOCTOU lint, pessimistic
and advisory locks — but it cannot exclude everything: two paths that
lock the same rows in opposite orders can still meet in the middle, and
Postgres breaks such a tie by aborting one transaction with SQLSTATE
`40P01` (deadlock detected) or `40001` (serialization failure). Until
this decision, that abort reached the person behind the request as a 500
for a document nothing was wrong with. Odoo retries every RPC up to five
times on exactly these two codes; the measurement that opened this task
found zero handling of either code in the backend.

## Decision

**A request the database aborted with SQLSTATE 40001 or 40P01 is
replayed whole, up to a small attempts limit, by a pure ASGI middleware
(`app/core/db_retry.py`) — but only when the aborted transaction had no
effects a rollback cannot undo. That condition is enforced by a
mechanism, not a convention: the choke points that reach the outside
world (a bare `EventBus.emit`, the email entry points, file-storage
writes, the LLM clients, webhook delivery) mark the running attempt, and
the middleware refuses a replay of a marked one.**

The unit of replay is the request, because the unit of work is the
request: `get_async_db` commits once before the response is written, so
an abort there means the response never started and the request can
honestly run again — on a fresh session and transaction, with its body
served from a single recording (bounded by a byte cap; an upload is
never buffered just to be retried). Two further gates are mechanical: a
response that already started its first byte is never replayed, and a
tainted attempt is handed the failure as before.

Events emitted through the transactional outbox are exempt from the
ledger: they are rows in the request's own transaction, so the rollback
that precedes a retry takes them with it. A bare `emit` — an XADD to the
stream before the commit — marks, which is one more reason to prefer the
outbox where the event must agree with the transaction.

### Alternatives considered

| Option | Why rejected |
|---|---|
| SERIALIZABLE everywhere with retry | The whole architecture deliberately is not that (ADR-020 context); swapping isolation levels to justify a retry loop inverts the means and the end |
| Retry inside the session dependency (`get_async_db`) | The dependency sits below the endpoint: it can re-commit, but it cannot re-run the endpoint whose work the commit lost |
| Wrap each route's handler | FastAPI ≥ 0.141 parks `include_router` behind lazy `_IncludedRouter` wrappers that materialise their own route copies at match time, so wrapping the original route objects covers nothing that was included — measured: 4 direct routes wrapped, 569 reachable, included requests bypassing the guard |
| Retry only routes that opt in | An opt-in list and a safety ledger solve the same problem from opposite ends; the ledger is checkable (a choke point either marks or it does not), an opt-in list rots silently |

## Consequences

**Positive**

- A deadlock between two lock-ordered paths now costs the loser a few
  milliseconds instead of a 500; the user sees the answer, not the
  database's tie-break.
- The retry re-enters only the app: one request keeps one request id,
  one rate-limit count, one performance record.
- Every effect-bearing path has a named choke point that marks it, which
  is also a map of what still needs moving behind the outbox to become
  replayable.

**Negative**

- A request that fires an external effect before its transaction ends
  keeps today's behaviour (the failure stands). That is the safe side:
  the alternative is a second email, a second webhook, a second bill.
- The body of a replayed request was buffered once (under the cap) —
  a cost paid only on the paths that actually collide.
- The choke-point ledger is only as complete as the choke points: a
  service that performs a new kind of outbound call outside them must
  add a mark, and nothing in the tree forces it to remember.

## References

- `backend/app/core/db_retry.py` — the middleware, the ledger, the body
  recording.
- `backend/tests/integration/test_a_deadlocked_request_is_retried_not_500ed.py`
  — a real two-session deadlock: without the guard a 500, with it a 200
  on the second attempt; a request that emitted before the failure is
  not replayed.
- `docs/adr/ADR-020-cost-layers-lock-per-product-not-per-shelf.md` —
  the lock discipline this is the net under.
