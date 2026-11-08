# Scaling Runbook

Operational guide for running Inventari with **more than one backend replica**.
Read this in full before adding replica #2 — several subsystems required
hardening to become cluster-safe (see the table below for what is covered).

---

## 1. Pre-replica checklist

Before scaling `backend` beyond one replica, verify every item:

### 1.1 Reverse proxy → real client IPs
- Gunicorn runs with `--forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"` (so
  `'*'` unless you set `FORWARDED_ALLOW_IPS`; already in
  `docker-compose.prod.yml` / `backend/Dockerfile`) so uvicorn's
  ProxyHeadersMiddleware rewrites `request.client.host` from
  `X-Forwarded-For`. The backend port is only reachable on `app-network`
  (Caddy is the sole hop), so `'*'` is safe.
- **Verify after deploy:** backend access logs must show real client IPs,
  not the Caddy container IP. Rate limiting buckets per client (issued API
  key → signed JWT user → IP); without this, the whole instance shares one
  200/min bucket. An API key is checked against the issued keys before it is
  counted, so a key nobody issued counts under the IP it came from.

### 1.2 Database migrations — single runner
- `backend/entrypoint.sh` wraps `alembic upgrade heads` + module migrations
  in a PostgreSQL advisory lock (`pg_advisory_lock(727301)`), so concurrent
  replica starts cannot race migrations. This is a **stop-gap**.
- The same lock is taken by a database rebuild (`demo reset`, `db reset`) for
  the whole drop-and-seed, so a backend starting beside one waits for it
  instead of migrating into a schema that is being dropped. The reset's
  connection names itself (`app.cli._migration_lock`) and the sweep before
  `DROP SCHEMA` spares that name: a backend waiting on the lock is not a
  session the reset may terminate, and ending it would make the entrypoint
  exit into a restart and a second migration pass.
- **The lock connection must not go through PgBouncer.** `pg_advisory_lock` is
  session-scoped; in `POOL_MODE: transaction` the lock and the matching unlock
  can land on different server connections, leaving a lock nobody holds and
  every other replica waiting on it. `docker-compose.prod.yml` therefore sets
  `MIGRATION_DATABASE_URL` straight at the `db` service, and only the
  entrypoint and the `db` CLI commands read it — the application keeps using
  the pooled `DATABASE_URL`.
- Target state: run migrations as a **one-shot deploy job**
  before rolling out new replicas, and drop the entrypoint lock. That would
  also retire `MIGRATION_DATABASE_URL`, since the job holds its own connection.

### 1.2.1 Pre-flight check — `db doctor`
The entrypoint runs `manage.py db doctor` inside the lock, before any
migration. It compares every module's `alembic_version_<module>` table with
its migration chain and refuses the boot when the schema is *ahead* of the
version table — the state that once crash-looped the backend after an
out-of-band schema change left the version table behind:
the pending migration re-creates DDL that already exists, fails, and
`restart: unless-stopped` runs it again.

```bash
docker compose exec -T backend python manage.py db doctor
# drift → exit 1 plus the exact repair command, e.g.
#   python manage.py db stamp-module shopping_lists 002_item_template
```

What the doctor deliberately lets through, because blocking it would stop
ordinary deploys: an empty database (every fresh install), a version behind
head with no sign of the pending DDL (every normal deploy), and an empty
version table whose tables all come from the core baseline — `db
upgrade-modules` already stamps that case itself.

`db stamp-module <name> <revision>` writes the version table without running
migrations, and **verifies first** that the tables that revision's chain
creates actually exist (`to_regclass`). Stamping ahead of the schema would
hide missing DDL until the first query fails; `--force` overrides for the case
where the tables live under a different name.

### 1.3 Connection pool math
Per gunicorn worker the app opens:

| Pool | Size | Max overflow | Total |
|---|---|---|---|
| sync engine | 20 | 10 | 30 |
| async engine | 10 | 10 | 20 |
| **per worker** | | | **50** |

**Rule:** `WEB_CONCURRENCY × 50 × replicas` must stay below PgBouncer
`MAX_CLIENT_CONN`, and PgBouncer `DEFAULT_POOL_SIZE` (server-side) must fit
under Postgres `max_connections` with headroom for admin/migration sessions.

Current prod default: `WEB_CONCURRENCY=4`, 1 replica → 200 client
connections (`MAX_CLIENT_CONN: 300`) → PgBouncer pool 30 → PG max 50. Adding
replica #2 doubles the client side to 400 — raise `MAX_CLIENT_CONN`
accordingly and re-check the server-side pool. `MAX_CLIENT_CONN` is set in
`docker-compose.prod.yml` (`pgbouncer-main`), not from `.env`, so
`WEB_CONCURRENCY=6` on one replica (300 client connections) already reaches it.

### 1.4 File storage must be shared
- Local disk storage (`FILE_STORAGE_BACKEND=local`, `uploads_data` volume)
  lives on one host. Replicas of the same compose project on that host mount
  the same named volume and see the same files; replicas on a second host
  would each see their own, so more than one host needs shared storage.
- Before replica #2: switch to S3 (`FILE_STORAGE_BACKEND=s3` +
  `FILE_STORAGE_S3_*` settings) after copying the upload files to the bucket
  under their existing keys. The backend is switchable by config only — rows
  name storage keys, not addresses, so the switch rewrites nothing; see
  `docs/subsystems/FILE_STORAGE.md` for the key contract and the copy.

### 1.5 Redis topology
- `redis` (main): cache, event/task streams, WebSocket hub — `allkeys-lru`.
  Eviction is acceptable; streams are capped (`EVENT_STREAM_MAXLEN`,
  `TASK_STREAM_MAXLEN`) and pending entries are reclaimed by the reaper.
- `redis-critical`: token blacklist + rate limiter — `noeviction`, 64 MB.
  `docker-compose.prod.yml` already sets
  `REDIS_CRITICAL_URL=redis://:${REDIS_PASSWORD}@redis-critical:6379`; a
  stack of your own needs the same URL, password included. Without it, both fall back to the main
  instance (`REDIS_URL`) — acceptable in dev, **not** in prod under memory
  pressure.

### 1.6 Stateless app containers
No in-process state may be required for correctness. With the changes in
the table below this holds for: scheduled tasks, event handlers, webhook retries,
email delivery, rate limiting, token revocation. Uploads are the exception
until 1.4 is done.

---

## 2. Cluster-safety table

| Subsystem | Before | After |
|---|---|---|
| Rate limiting | one bucket per instance (proxy IP) | per issued API key / signed JWT user / real client IP, each capped by `RATE_LIMIT_PER_IP` |
| Scheduler periodic tasks | ran on every worker (N× duplicates) | Redis tick-lock (`SET NX EX`, TTL ~80% of interval) — one node per tick |
| Webhook settings migration | 1 Hz loop forever, per worker | one-shot at startup (idempotent) |
| Webhook worker registration | registered twice | single registration (test-guarded) |
| Equipment notifications | duplicate insert per run per worker | natural-key dedup (org + reference + type + day, unread only) |
| Event bus | local fire-and-forget **and** XADD → ~75% double handling with 4 workers | stream-only in prod; consumer group = one delivery, handlers run before the ACK (at-least-once — see below); no-Redis fallback is fail-open + logged |
| Event stream | unbounded growth, no reclaim | `EVENT_STREAM_MAXLEN` (approx) + XAUTOCLAIM reaper (5 min tick) |
| Task stream | unbounded growth, no reclaim | `TASK_STREAM_MAXLEN` + reaper |
| Webhook retry | `FOR UPDATE` held across HTTP calls | claim-then-deliver; locks released before HTTP; a claim older than twice the endpoint's `timeout_seconds` (20 s at the default 10) is reclaimed |
| Webhook first attempt | fire-and-forget, no trace | PENDING row committed before the HTTP call; stale PENDING requeued |
| Transactional events | emit after commit → crash loses event | `event_outbox` + relay; `emit_transactional` rides the business transaction (at-least-once) |
| Emails | thread-pool SMTP, no retry | `email_jobs` table + claim/send/retry worker, FAILED after max attempts |
| Redis eviction | blacklist/limiter on allkeys-lru | dedicated `noeviction` instance |
| Migrations on multi-replica start | race possible | `pg_advisory_lock` in entrypoint (stop-gap) |

### Event delivery: at-least-once, and what that costs

"Consumer group = exactly one execution" described the delivery, not the
handlers. The consumer acknowledged the message on the line after the
dispatch call, and outside tests that call started each handler in a
detached `asyncio.create_task` and returned — so the ACK landed before any
handler had run, and a worker that died in that window left nothing
pending for XAUTOCLAIM to reclaim. The stated guarantee was *exactly
once*; the real one was *at most once*.

The consumer now awaits the handlers and acknowledges after them, so:

- **Handlers must tolerate a repeat.** A worker that dies after a handler
  ran but before the ACK leaves the message pending, and the reclaim runs
  the handlers again.
- **One handler holds the node's stream.** Handlers run in sequence, in
  the priority order `subscribe` already claimed to sort by, and each is
  bounded by `HANDLER_TIMEOUT_S` (30 s). Halfway to the bound a warning
  names the slow handler while it still runs, because everything later on
  this node is queued behind it. A handler that outlasts the bound, or
  raises, is written to the delivery log and the message is acknowledged
  for the rest: the retry worker runs that handler alone again, up to
  `MAX_HANDLER_ATTEMPTS` times with doubling backoff, then parks it as
  `dead` and warns the organization's admins (the instance's superusers
  for an event of no organization). So a handler must be
  idempotent — the contract is in the docstring of `EventBus` in
  `backend/app/core/_event_bus.py`.
- **Shutdown drains.** `disconnect()` lets the loop finish what it is
  holding, up to `SHUTDOWN_DRAIN_S` (10 s), then cancels — and what was
  cancelled stays unacknowledged, which is the point.

**After a node dies — how long until the message runs again.** A message
a dead worker had read is redelivered by `XAUTOCLAIM` once it has been
unacknowledged for `STREAM_CLAIM_IDLE_MS` (60 s), and only when some node
runs the stream reaper. The reaper runs on every node at startup (after the
modules have subscribed their handlers) and then on a 5-minute tick, one
node per tick. So the worst case is **about 6 minutes** (the 5-minute tick
plus the 60 s idle window — measured: 5 min 43 s), and it is much shorter
when a node starts later than 60 s after the crash, because that startup run
finds the message already idle. It depends on three numbers: the idle window,
the tick interval and how long the replacement takes to start. A handler
that failed (rather than a worker that died) does not wait for any of this:
the retry worker runs it with its own backoff. Consumers are named after the
process: a clean shutdown of the event bus removes its own from the group, and the reaper
removes any that has held nothing for an hour, so `XINFO CONSUMERS` does
not grow with every restart.

Emission itself is still the caller's problem to get right: `emit` is an
XADD after the commit, so it can be lost in a crash and can announce a
transaction that then rolls back. `emit_transactional` writes to the
outbox inside the transaction and is the fix. The architecture lint holds
a baseline of function/event keys (`app/core/bare_emit_baseline.txt`); a
new key fails the gate. The key is `relative/path.py::function::event`,
not a call site: repeated emits of the same event in the same function
share one entry, so an additional call there remains invisible. This
boundary is deliberate: keying by line would treat a refactor as a new
emission.

### Deliberately out of scope
- `audit_log` retention/purge — owner decision pending; trigger blocks
  UPDATE/DELETE by design.
- Contract versioning — marketplace decisions. Module sandboxing is not a
  deferred item next to it:
  [ADR-019](adr/ADR-019-modules-are-certified-not-sandboxed.md) closed it —
  module trust here is certification and the operator's own choice, not
  confinement.
- Per-module permissions — need a redesign before they can gate module access.

---

## 3. Monitoring after scaling

- **429s**: should only fire per-client; a global 429 spike means proxy
  headers are not trusted (re-check 1.1).
- **Streams**: `XLEN` on `inventari_stream` / `inventari_tasks` should stay
  well under the MAXLEN caps; `XPENDING` should trend to 0 (reaper lag
  otherwise).
- **Outbox**: `SELECT count(*) FROM event_outbox WHERE published_at IS NULL`
  should trend to 0; sustained growth = relay down or Redis unreachable.
- **Email jobs**: watch `status='failed'` rows (poison after max attempts).
- **Webhook deliveries**: `delivery_status='pending'` older than ~5 min is
  requeued automatically — a growing count means the retry worker is down.
- **Scheduler**: `[Scheduler] Tick skipped (lock held by another node)` in
  logs is expected on multi-node; missing entirely on all nodes means the
  lock Redis is down (tasks then run per-node — check notification dedup
  pressure).
