# Webhooks Subsystem

The **Webhooks** module delivers outbound HTTP notifications to external systems whenever Inventari events occur. It follows the same pattern as GitHub Webhooks: signed payloads, configurable retries, and a circuit breaker.

## Architecture

```
SystemEvent (EventBus)
      │
      ▼
WebhooksModule.on_modules_ready()   ← subscribes to every subscribable event
      │                                      (SystemEvent plus the events modules register)
      │
      ▼
dispatch_event(event, payload)   ← opens its own sessions
      │   ├─ queries WebhookEndpoint rows (org-scoped, active, event_type match)
      │   ├─ commits a `pending` WebhookDeliveryLog row per endpoint
      │   └─ asyncio.gather(*[_attempt_delivery(wh, …) for wh in matching])
      │
      ▼
_attempt_delivery(webhook, payload_bytes, outbound, delivery_id=…)
      │   ├─ SSRF guard  (app/core/ssrf_guard.py — ipaddress + socket.getaddrinfo
      │   │              with IP pinning; blocks private/loopback/link-local)
      │   ├─ HMAC sign   (signing.py — X-Inventari-Signature-256: sha256=…)
      │   └─ httpx POST/PUT (connects to the pinned IP, no DNS rebinding window)
      │
      ▼
WebhookDeliveryLog  (payload_json JSONB, status_code, response_body, error_message)
```

## Database Tables

| Table | Key columns |
|-------|-------------|
| `webhook_endpoints` | id, organization_id, name, url, secret (Fernet-encrypted), http_method (`POST` or `PUT`), event_types (JSONB array), max_retries, consecutive_failures, is_active, auto_disabled_at (set only by the circuit breaker) |
| `webhook_delivery_logs` | id, webhook_endpoint_id, event_type, payload_json (JSONB), delivery_id, delivery_status (`pending`, `pending_retry`, `retrying`, `success`, `failed`), attempt_number, next_retry_at, claimed_at, abandon_reason |

## Security

- **HMAC-SHA256** signing: `X-Inventari-Signature-256: sha256=<hex>` header (GitHub style). Sent when a secret is configured *and readable*. A secret that cannot be read — written under a rotated key, or edited in the table — refuses the delivery outright (the attempt fails with a named reason, the failure counter moves, the breaker eventually cuts the channel off) instead of sending an unsigned payload a receiver cannot tell from a channel that never signed.
- **Secret storage**: encrypted at rest using Fernet via `CoreSecretsAPI` (`app.core.public_api.secrets`). API responses expose `has_secret: bool` only — never the raw value.
- **SSRF guard** (`app/core/ssrf_guard.py`): **blocks** any address that is not
  globally routable — RFC-1918, loopback, link-local, ULA, carrier NAT
  (`100.64.0.0/10`, where a Tailscale address lives), benchmarking, the
  documentation ranges and IPv4-mapped IPv6 — **and** hostnames whose DNS
  resolution lands on one. The rule is `ipaddress.is_global`, not a list of
  ranges: a list is how three of those pools came to be missed, so that a Home
  Assistant reached over Tailscale was accepted without any switch while the
  same box on the LAN was refused. Hostnames are resolved via
  `socket.getaddrinfo` and the resolved IP is **pinned** for the HTTP request
  to prevent DNS rebinding (TOCTOU) attacks.
- **Reaching your own network**: set `WEBHOOKS_ALLOW_PRIVATE_NETWORKS=true` in
  `.env` and restart (`docker compose up -d backend`). Both compose files pass
  the variable through; the backend service has no `env_file:`, so a variable
  they do not name never reaches the container. Default `False` — flip it on a
  self-hosted install that needs Home Assistant on `192.168.x.x`, and leave it
  off wherever more than one organization is served: the organization admin
  types the URL, so on means they choose what this server connects to.
  `LLM_ALLOW_PRIVATE_NETWORKS` is the same decision for a local model server
  and is deliberately separate.

## Circuit Breaker

After `consecutive_failures >= circuit_breaker_threshold` (default 10, a per-organization module setting between 3 and 100), the endpoint is automatically set `is_active = False`. Admins receive a notification and must reactivate manually via `POST /api/v1/webhooks/endpoints/{id}/reactivate`.

## Retry Worker

Every 60 seconds the `webhooks_retry_failed` TaskScheduler task queries delivery logs with `delivery_status = 'pending_retry'` and `next_retry_at <= now`. It also requeues first attempts left `pending` for more than 5 minutes (a crash mid-delivery) and reclaims `retrying` claims older than twice the endpoint's `timeout_seconds`. A delivery that still fails after `max_retries` retries ends as `failed`. Backoff is exponential with jitter:
`retry_backoff_seconds * 2 ** (attempt - 1) + random.uniform(0, base * 0.25)`, capped at 3600 s.

## Log Cleanup

Every 24 hours `webhooks_cleanup_logs` deletes delivery logs older than `log_retention_days` (default 30). Configurable per-org via Module Settings.

## API Endpoints (`/api/v1/webhooks/`)

Every route sits behind the module guard and an administrator check declared on
the router itself (`router.py`): a member who is not an administrator is refused
reads as well, because an endpoint's URL is itself a credential at most receivers.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/events` | JWT + admin | List available event types |
| GET | `/endpoints` | JWT + admin | List org webhooks |
| POST | `/endpoints` | JWT + admin | Create webhook |
| GET | `/endpoints/{id}` | JWT + admin | Get single webhook |
| PUT | `/endpoints/{id}` | JWT + admin | Update webhook |
| DELETE | `/endpoints/{id}` | JWT + admin | Delete webhook (cascade logs) |
| POST | `/endpoints/{id}/test` | JWT + admin | Send test ping |
| POST | `/endpoints/{id}/reactivate` | JWT + admin | Re-enable after circuit break |
| GET | `/endpoints/{id}/deliveries` | JWT + admin | Paginated delivery log |

## Payload Format

```json
{
  "schema_version": 1,
  "event": "item.used",
  "timestamp": "2026-03-10T12:34:56.789123+00:00",
  "delivery_id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "org-uuid",
  "data": { "item": { "...": "the full item snapshot" }, "quantity": 2, "user_id": "user-uuid" }
}
```

### Delivery identity

`delivery_id` is minted once per delivery — one (event, endpoint) pair — and
carried both in the body (above) and in the `X-Inventari-Delivery` header on
**every attempt**, first send and retries alike. A receiver may therefore
dedup by it, GitHub-style: a retry of a delivery you already processed
arrives under the same id and can be dropped. Two different endpoints
receiving the same event get two different ids, because each endpoint's
delivery is its own row.

The delivery history in the operator panel shows the same id, so a row there
can be matched against a receiver's log.

### Checking freshness

The signature (`X-Inventari-Signature-256`) covers the **body only**; no header
is signed. A receiver that wants replay protection therefore reads `timestamp`
from the signed body — after verifying the signature, never before — and
refuses a delivery whose timestamp is older than the window it accepts. A
retry resends the stored body — same `delivery_id`, same `timestamp`, the
same bytes and so the same signature: the body is written with its keys
sorted on every attempt, so the JSONB copy the retry reads back gives the
bytes the first attempt sent — which means a retry made after the backoff (up
to an hour) can arrive older than a short window. A receiver with a
tight window should dedup by `delivery_id` first and treat a stale timestamp
on an id it has not processed as "late", not as "forged".

### The test ping

`POST /endpoints/{id}/test` sends a `webhook.test` event in the same envelope
as a real delivery — `schema_version`, `event`, `timestamp`, `delivery_id`,
`organization_id`, `data` — with `data` holding `webhook_id` and a `message`.
A receiver that validates the ping validates the first real event.

### Who did it — `data.user_id`

Every item event (`item.created`, `item.updated`, `item.deleted`, `item.moved`,
`item.used`, `item.disposed`) carries the acting account in one key,
`data.user_id`: the account's id, or `null` when a system path acted on nobody's
behalf (a quantity written by an import or a scheduled task, for example). The
key is always present, so a missing key never has to be read as "this event
does not say". No event carries a `data.user` object for the actor; the one
`data.user` that remains belongs to the membership events
(`user.joined_organization`, `user.left_organization`), where it is the member
the event is about: `{id, email, full_name, role}`.

### One move, two events

Moving an item emits **both** `item.updated` (`changes.storage_location_id`
holds the new place) and `item.moved` (`changes.from_storage_id` and
`changes.to_storage_id`). That is deliberate — `item.updated` is the "something
about this record changed" feed and `item.moved` the specific one — but it means
a receiver subscribed to both counts one move twice. Subscribe to `item.moved`
alone to hear about moves, and to `item.updated` for everything else.

### A dispatch handed to a carrier — `document.shipped`

Completing a dispatch (`OUT` or `INTERNAL_OUT`) with a shipment emits
`document.shipped` beside `document.completed`, in the same transaction. It is
a topic of its own rather than more keys in `document.completed`: that event
fires for every document type and names no document number, so a receiver
that books shipments would have to listen to every receipt and stock take to
find the dispatches among them. A completion without a shipment emits no
`document.shipped`.

```json
"data": {
  "document_id": "…",
  "document_number": "OUT/2026/0042",
  "document_type": "OUT",
  "carrier": "InPost",
  "tracking_number": "620012345678901234567890",
  "tracking_url": "https://inpost.pl/sledzenie-przesylek?number=620012345678901234567890",
  "package_count": 2,
  "shipped_at": "2026-10-17T09:12:00+00:00",
  "lines": [ "…" ]
}
```

`carrier` is the name as the operator typed it. `tracking_number` is `null`
for a hand-over without one, and `tracking_url` is `null` when there is no
number or no template names the carrier — the organization's templates in
the document profile are read first, then the built-in ones (InPost, DHL,
DPD, GLS, Poczta Polska, UPS, FedEx). `package_count` is the dispatch's
packages, `0` when it was not packed.

### What the document events say moved

`document.confirmed`, `document.completed`, `document.cancelled` and
`document.shipped` each carry `data.lines`, one entry per document line (and
per batch, see below), so a receiver learns what the document was about without fetching it:

```json
"lines": [
  {
    "source_po_line_id": null,
    "done_quantity": 4.0,
    "expected_quantity": 4.0,
    "product_id": "…",
    "product_code": "SKU-001",
    "lot_id": "…",
    "lot_number": "LOT-7",
    "source_location_id": null,
    "source_location_code": null,
    "target_location_id": "…",
    "target_location_code": "A-01",
    "unit": "pcs"
  }
]
```

`done_quantity` is `0` until the line is executed. `lot_number` is the batch
or serial number the line names, else that of the stock record it moves,
`null` for stock with none; `lot_id` is the batch record and stays `null`
until it exists — a confirmed receipt has not created it yet. The shelves
follow the posting direction. A dispatch or a scrap names the shelf it takes
from and no target, because the goods leave the stock; any other document
names the shelf the line takes from (else the document's source) and the one
the goods landed on, else the one named ahead of execution, else the
document's target. A code is the shelf's short code, or its name when it has
none.

A dispatch or a scrap that names no batch takes from whatever the records
hold, so the lot of the stock record a line points at says nothing about what
left. Once posted, such a line is reported as one entry per batch the draw
actually took, each with its own `lot_id`, `lot_number` and `done_quantity`;
`expected_quantity` stays on the first entry and is `0` on the rest, so the
entries sum to the line. Summing `done_quantity` by product, batch and shelf
reproduces the movements the document posted. Keys are only ever added to a line, never removed or renamed.

### Switching the module off

The module's own switch is the one event that still goes out after the module is
off: when Webhooks is switched off (from the store, a profile change or focus
mode), endpoints subscribed to `module.disabled` receive it with
`data.module_name == "webhooks"` before the sending stops, so a listener can tell
"the organization turned this off" from "nothing changed". Nothing else leaves
while the module is off, and that announcement is sent once — a failed first
attempt is not retried, because the retry worker also stops when the module is
off. Other modules going off while Webhooks is off are not announced.

### Envelope versioning

`schema_version` says which shape the envelope is speaking, so a consumer can
tell a changed contract from a bad day instead of guessing. It versions the
envelope — `event`, `timestamp`, `delivery_id`, `organization_id`, `data` —
not the contents of `data`, which follow whatever the payload model for that
event declares.

The rule is **additive changes do not bump it**. Adding a key a reader can
safely ignore, or widening a field, keeps `schema_version` where it is: a
consumer that ignores the new key keeps working, and one that wants it can
start reading it without a version negotiation. The number moves only on a
change a consumer must react to — a key removed or renamed, a type changed, a
field re-nested.

History:

| `schema_version` | Change |
|---|---|
| `1` | The version itself. Every key that shipped before it is unchanged; this release is the additive change par excellence. |

## Frontend

Located in `frontend/src/modules/webhooks/`:

```
module.ts          — registration (auto-discovered)
i18n/en.json
i18n/pl.json
i18n/de.json
i18n/fr.json
i18n/es.json
i18n/pt.json
api/
  webhooks.ts             — API client
  webhooks.test.ts
hooks/
  useWebhooks.ts
  useWebhooks.test.tsx
pages/
  WebhooksPage.tsx        — CRUD list page
  WebhooksPage.test.tsx
components/
  WebhookForm.tsx         — Create/edit form with event type selector
  WebhookForm.test.tsx
  WebhookDeliveryLogs.tsx — Paginated delivery log with payload inspector
  WebhookDeliveryLogs.test.tsx
  WebhookCard.tsx
  WebhookCard.test.tsx
types/
  webhooks.ts
```

## Architecture Compliance

- `models.py` imports `Base` from `app.database` (the standard Core declarative base) ✅
- `webhook_service.py` and `router.py` use `app.core.public_api.CoreSecretsAPI` for encryption ✅
- No `app.services.*` direct imports in module files ✅
- Architecture linter: `Architecture lint passed` ✅

## Related

- Backend module: `backend/app/modules/webhooks/`
- Migrations: `app/modules/webhooks/migrations/versions/001_initial.py`, `002_claimed_at.py`, `003_auto_disabled_at.py`, `004_delivery_history.py`, `005_timestamps_carry_their_zone.py` (the legacy `b3ac35f4da34` lives in `backend/migrations/versions_archive/`)
