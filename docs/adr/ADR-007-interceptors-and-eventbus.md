# ADR-007: Two Extension Mechanisms — Interceptors (sync) and EventBus (async)

## Status

Accepted — 2026-06-22

## Context

Module authors repeatedly ask: **"Why can't I mutate data in an event
handler?"** or **"Why are there two extension mechanisms instead of one?"**
The answer is a deliberate separation of concerns between synchronous,
in-request mutation (interceptors) and asynchronous, post-response side
effects (event bus).

The original concern: if a module needs to react to "an item was created,"
there are two fundamentally different needs:

1. **Block or modify the operation** before it commits (validate, enrich,
   enforce policy). This must happen synchronously, within the request
   transaction.
2. **React to the operation after it succeeds** (send notification, deliver
   webhook, update analytics, invalidate cache). This should not block the
   user's request or risk failing it.

Mixing these into one mechanism produces a common anti-pattern: modules try
to mutate data in async event handlers, but the transaction has already
committed, or the handler fails and silently corrupts state.

## Decision

**Two distinct extension mechanisms with non-overlapping semantics.**

| | Interceptors | EventBus |
|---|---|---|
| **Execution** | Synchronous, in-request, within the DB transaction | Asynchronous, post-response, via Redis Streams (without Redis, handlers run inline as a fail-open fallback) |
| **Can mutate data** | **Yes** — before-hooks receive the data and may change it | **No** — receives an event payload to read |
| **Can block operations** | **Yes** — raise an error to abort | No |
| **Ordering** | Priority-based pipeline (deterministic) | Consumer Group ordering (best-effort) |
| **Persistence** | In-process (lost on restart) | Redis Streams (survives restart) |
| **Failure handling** | A before-hook aborts the operation (error propagates to caller); an after-hook's error is logged | Handler failure logged, does not affect the operation |
| **Use case** | Validation, enrichment, policy enforcement, approval gates | Notifications, webhooks, audit log, cache invalidation, analytics |

### InterceptorPipeline (`app/core/interceptors.py`)

Synchronous before/after hooks for Item, Storage, and Category CRUD. Modules
register interceptors that can mutate data or block operations by raising.

```
Request → [before_interceptors] → DB write → [after_interceptors] → Response
```

Example: the `stock_takes` module registers `StockTakesPurgeBlocker`, an item
interceptor that refuses to purge a record while a stock take is counting it
(`backend/app/modules/stock_takes/interceptors.py`).

### EventBus (`app/core/_event_bus.py`, re-exported by `app/core/events.py`)

Asynchronous pub/sub with Redis Streams persistence and Consumer Groups.
36+ system events defined at the time (28 `SystemEvent` members on 2026-10-31; module-owned events live in the modules). Handlers receive an event payload
and run after the response is sent.

```
DB commit → [event published to Redis Stream] → Response sent
                                                 ↓ (async)
                                          [consumer group handlers]
```

Example: the `webhooks` module subscribes to `item.used` and delivers
outbound HTTP notifications — if the webhook endpoint is down, the item
use still succeeded.

### Why not one unified mechanism?

A single "hook" system that tries to serve both purposes hits a fundamental
contradiction:

- If it's synchronous, side effects (webhooks, notifications) block the user
  request — a slow webhook server makes the app feel slow.
- If it's asynchronous, mutation/validation can't happen before the commit —
  a module can't enforce "items without a category are rejected."

The two-mechanism split resolves this: **mutation/validation is synchronous
and blocking (interceptors); side effects are asynchronous and non-blocking
(event bus).**

## Consequences

### Positive

- **Clear contract for module authors.** Need to validate/mutate? Use an
  interceptor. Need to react? Subscribe to an event. No ambiguity.
- **Fault isolation.** A failing event handler (e.g., webhook endpoint down)
  does not block or fail the user's request. A failing before-interceptor
  correctly aborts the operation (that's its job).
- **Independent scaling.** Event handlers can be slow (PDF generation, email
  sending) without affecting request latency. Interceptors must be fast
  (they're in the critical path).

### Negative

- **Two APIs to learn.** Module authors must understand both mechanisms and
  when to use each. Mitigated by clear documentation and the table above.
- **No mutation in event handlers.** A module that needs to update state
  based on an event must use a separate write (its own DB transaction in the
  handler). This is by design but can surprise newcomers.

### Risks

- **"I'll just use the event bus for everything" anti-pattern.** A module
  author puts validation logic in an event handler, discovers it runs after
  commit, and the invalid data is already persisted. Mitigation: documentation
  + code review (the interceptor API is the documented path for validation).
- **Interceptor performance.** Since interceptors are synchronous and in the
  critical path, a slow interceptor degrades all requests. Mitigation:
  interceptors should be fast (DB reads, in-memory checks); heavy work goes
  to the event bus.

## Implementation

- **Interceptors:** `backend/app/core/interceptors.py` —
  `InterceptorPipeline` with priority-based registration.
- **EventBus:** `backend/app/core/_event_bus.py` (class `EventBus`, singleton
  `event_bus`, re-exported by `backend/app/core/events.py`) — Redis Streams
  with a consumer group; `emit()` / `emit_transactional()` publish,
  `subscribe(event, callback, priority)` registers a handler.
- **Events catalog:** 36+ system events then, 28 on 2026-10-31 (e.g.,
  `item.created`, `item.used`, `location.created`, `label.scanned`).
- **ContributionRegistry:** `backend/app/core/contributions.py` — also
  exposes `item_interceptors`, `storage_interceptors` and
  `category_interceptors` slots for module
  registration.

## References

- `docs/TECHNICAL_DECISIONS.md` §11 (original rationale + comparison table)
- `backend/app/core/interceptors.py`
- `backend/app/core/events.py`
- `backend/app/core/contributions.py`
- ADR-008 (isolation strategy — interceptors and event bus are part of the
  multi-layer guardrail design)
