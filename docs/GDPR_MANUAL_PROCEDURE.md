# GDPR Manual Procedure (Data Subject Requests)

Status: **Manual procedure**.

**Who this is for.** Whoever runs an instance of Inventari: the operator, who
decides what is stored on it and for whom, and so is normally the *controller*
in GDPR terms. The procedure is yours to carry out; the project's maintainers
do not hold your instance's data.

**The public demo needs none of it.** A demo visitor signs in with one click to
a sandbox organization of their own. The account in it is generated
(`visitor-<random>@sandbox.example.com`, named "Demo Visitor"), nobody is asked
for an address, and the nightly rebuild deletes every organization, account and
file created there. The one thing the demo keeps is the network address in the
server logs, for seven days (see [DEMO.md](DEMO.md#logs)).

Accounts on a real instance come from an operator's approval of a
`RegistrationRequest`, from an invitation issued by an organization
administrator, or as the first account of an empty installation. There is no
open self-serve signup and no self-serve export or erasure, so every data
subject request is handled by hand. This document is the manual procedure for
that.

> **When this procedure applies:** it covers deployments without a
> self-serve export/erasure flow. Export and erasure MUST be automated
> (self-service or admin one-click) before public signup is opened; until
> then the manual steps below are the equivalent handling.

## Where requests arrive

The public privacy page (`/privacy`, linked from the sign-in screen) tells
people to ask the operator for a copy or deletion and promises the answer
below. It names the operator from `OPERATOR_NAME` and `OPERATOR_CONTACT` in
`.env`; set both, or the page can only tell them to ask whoever gave them
access.

## SLA

Answer a data subject request without undue delay and at the latest within
**one month** of receiving it (GDPR Art. 12(3)). The month can be extended by
**two further months** when the request is complex or there are many of them,
but the requester must be told of the extension, and why, within the first
month. The privacy page promises **30 days**; hold yourself to that, since it
is the date your users have read. Target internal handling time: **7 days**.

## Personal data inventory

The first rows are what the application holds *per account*; erasure
(`anonymize_user_async`) rewrites only `users`, `registration_requests` and
`organization_invitations`. The rows after them are records the organization
writes about people — often people who never had an account — and erasure
touches none of them: see *Records the organization owns*.

| Table | Personal data | Export | Erasure behaviour |
|---|---|---|---|
| `users` | `email`, `full_name`, `hashed_password`; `blocking_reason` — free text an operator may have written when blocking the account | yes (`blocking_reason` is not in the query below; add it if set) | email, name and password anonymized in place by `anonymize_user_async`; `blocking_reason` is **not** touched — clear it by hand if it names the person |
| `registration_requests` | `email`, `full_name` | yes | anonymized by `anonymize_user_async` |
| `organization_invitations` | `invited_email` — the address the code was issued for; `created_by`, `used_by_user_id` are UUIDs | yes | `invited_email` anonymized by `anonymize_user_async`; UUIDs kept |
| `audit_log` | `user_id` (UUID); on member and invitation entries the address itself: `snapshot.name` when a member is created, changed or leaves, `snapshot.invited_email` when an invitation is issued, resent, revoked or accepted; on equipment hand-over entries the holder's name (`snapshot.before.assigned_to` / `snapshot.after.assigned_to`); on partner entries the partner's name and, when a field changed, its old and new value (`snapshot.before` / `snapshot.after`, e.g. `email`, `phone`, `contact_person`) | yes for entries by the person and entries naming the address (member and invitation entries); entries that name a holder or a partner only by name are found with the queries under *Records the organization owns* | **kept as written**: rows are immutable in the database (`audit_log_immutable` trigger) — see *Records that keep the address* |
| `email_jobs` | `to_email`, `subject`; `html_content` quotes the address in the delivered body | yes (`to_email`, `subject`, timestamps) | kept — a copy of mail already delivered; rows deleted on request, see *Records that keep the address* |
| `item_history` | `user_id` (FK); on equipment `CHECKOUT` entries `changes.assigned_to`, the holder's name as typed at checkout | metadata (by `user_id`) | FK kept (audit value); the holder's name stays — see *Records the organization owns* |
| `stock_moves` | `created_by` (FK only) | no | FK kept |
| `items` / `item_attachments` | created/modified by user inside their org; no direct user PII columns | via org export | stays with the organization |
| `ai_usage_logs` | `user_id` (FK only) | metadata | FK kept |
| `notifications` | `user_id` (FK); `title` / `content` can quote a name — an overdue-equipment notice names the holder | no | FK kept; the text stays |
| `partners` | `name`, `email`, `phone`, `contact_person`, `address` (JSON), `tax_id`, `notes` — of suppliers, customers and employees; a natural person when `type = 'EMPLOYEE'`, when `is_consumer` is set, or a sole trader | yes, by query under *Records the organization owns* | **not touched** — belongs to the organization |
| `equipment_assignments` | `assigned_to_name`, `assigned_to_email` — free text, so a person without an account can hold an asset; `checkout_notes`, `checkin_notes` | yes, by query | **not touched** — organization record, matched to a person by address |
| `audit_responses` (equipment attestation campaigns) | `assignee_name`, `assignee_email`, and from the person's answer on the public link `response_ip`, `response_user_agent`, `dispute_reason` | yes, by query | **not touched** — organization record |
| `organizations` | `name`, `address`, `tax_id` — the organization's own business details; a sole trader's identify a person | no | **not touched** — edited by the organization |
| Refresh/access tokens | JWT in HttpOnly cookie / memory | n/a | revoked via `token_blacklist.revoke_user_family` |
| Technical logs — `LOG_DIR/app.log` (10 MB × 5 backups) and the container stdout | addresses and client IPs: failed-login and lockout lines write the account's address and the IP that tried it (`app.services.auth_service`), the mail lines write the recipient (`app.services.email_service`) | no | **kept** — erasure never writes a log file; see *Records that keep the address* |

## Export (right of access, Art. 15)

Run per user (replace `<USER_ID>` / `<EMAIL>`):

```sql
SELECT id, email, full_name, created_at, preferred_language, is_active
FROM users WHERE id = '<USER_ID>';

SELECT id, email, full_name, created_at, accepted_at, is_rejected
FROM registration_requests WHERE email = '<EMAIL>';

SELECT id, action, changes, created_at
FROM item_history WHERE user_id = '<USER_ID>' ORDER BY created_at;

-- Entries by this user, and entries that name the address in their
-- snapshot — an invitation the person never acted on is journaled by
-- whoever sent it, so filtering on user_id alone would miss it.
SELECT id, action, target_type, target_id, snapshot, created_at
FROM audit_log
WHERE user_id = '<USER_ID>'
   OR lower(coalesce(snapshot->>'name', '')) = lower('<EMAIL>')
   OR lower(coalesce(snapshot->>'invited_email', '')) = lower('<EMAIL>')
ORDER BY created_at;

SELECT id, organization_id, invited_email, role, is_used, used_by_user_id,
       created_at, expires_at, revoked_at
FROM organization_invitations
WHERE lower(invited_email) = lower('<EMAIL>');

SELECT id, to_email, subject, status, created_at, sent_at
FROM email_jobs WHERE lower(to_email) = lower('<EMAIL>');

SELECT id, product_template_id, quantity, state, created_at
FROM stock_moves WHERE created_by = '<USER_ID>' ORDER BY created_at;

SELECT id, provider, model_name, created_at
FROM ai_usage_logs WHERE user_id = '<USER_ID>' ORDER BY created_at;
```

Organization-scoped content (items, documents, attachments) belongs to
the organization, not the individual; include it only when the requesting
user is the organization owner and asks for an org export.

The organization's records that name the person by address or by name —
equipment holders, attestation answers, partner contacts — are not reached by
any query above, because they carry no user id. They are exported with the
queries under *Records the organization owns*.

## Erasure (right to be forgotten, Art. 17)

Use the service function (keeps audit FKs intact, destroys PII,
deactivates the account, revokes tokens). Put the user's id in place of
`<USER_ID>`; on a development stack the same script runs with
`docker compose exec -T backend uv run python -`.

```bash
docker compose -f docker-compose.prod.yml exec -T backend python - <<'EOF'
import asyncio
from uuid import UUID

import redis.asyncio as aioredis

from app import database
from app.cli import bootstrap_db
from app.config import settings
from app.core.token_blacklist import token_blacklist
from app.services.gdpr_service import anonymize_user_async

USER_ID = UUID('<USER_ID>')


async def main():
    # A script runs outside the web app, so it does what the app's startup
    # would: load every module's models, open the database engine, and
    # connect the Redis that token revocation writes to (production refuses
    # to revoke without it).
    bootstrap_db()
    database.init_async_engine()
    redis = aioredis.from_url(
        settings.REDIS_CRITICAL_URL or settings.REDIS_URL, decode_responses=True
    )
    token_blacklist.set_redis(redis)
    try:
        async with database.AsyncSessionLocal() as db:
            await anonymize_user_async(db, USER_ID)
            await db.commit()
        print(f'Erased user {USER_ID}')
    finally:
        await redis.aclose()
        await database.async_engine.dispose()


asyncio.run(main())
EOF
```

Effects (verified by `backend/tests/integration/test_gdpr_erasure.py`):

- `users`: email → `deleted-<uuid>@anonymized.invalid`, `full_name` →
  `Deleted User`, password hash replaced with random bytes,
  `is_active = false` (all JWT and API-key auth rejected immediately).
- `registration_requests`: matching rows anonymized, invite token cleared.
- `organization_invitations`: every invitation issued for that address has
  `invited_email` set to the same `…@anonymized.invalid` address. The code
  keeps its binding to an address — now one no account can hold, so it opens
  for nobody — rather than being cleared into a bearer link.
  `created_by` / `used_by_user_id` are UUIDs and stay.
- `item_history` / `audit_log` / `stock_moves`: rows preserved with the
  FK to the anonymized user (audit requirement); the UUID is not PII.
  Journal entries keep what they recorded, address included — see the next
  section.
- Outstanding tokens revoked via the token blacklist.

What the function does **not** touch: `users.blocking_reason`, the organization's
records about the person (`equipment_assignments`, `audit_responses`, `partners`,
the holder's name in `item_history` and `notifications`), the journal and the
logs. The next section covers what an operator does about each.

## Records that keep the address, and what to do with them

Erasure rewrites what can be rewritten. Three kinds of record still hold
the address afterwards, and each has an explicit handling. None of them is
handled by pretending the address is no longer there.

### Journal entries (`audit_log`) — kept, because they cannot be edited

A journal entry about a member or an invitation carries the address as its
name: `snapshot.name` when a member was created, changed or left, and
`snapshot.invited_email` when an invitation was issued, resent, revoked or
accepted. The
journal is the organization's record of who did what, and the database
refuses `UPDATE` and `DELETE` on it (`audit_log_immutable` trigger). An
erasure that rewrote those rows would have to switch that trigger off
first; a journal an operator can edit on request is not a journal.

**Handling:** the entries stay exactly as written. Answer the requester
plainly: the address remains in the organization's history of its members
and of who was invited, and it is not editable — it leaves the database
only with the entry itself, which is the journal's own retention question
(`docs/SCALING.md`), not this procedure's. Two tests carry that:
`backend/tests/integration/test_audit_log_is_immutable.py` is what makes
"not editable" a fact rather than a promise, and
`backend/tests/integration/test_gdpr_erasure.py` pins that erasure leaves
the entries alone while scrubbing the invitation row beside them.

### Delivered mail (`email_jobs`) — kept, deletable

The queue keeps the mail it delivered: `to_email`, `subject` and
`html_content`, whose body quotes the address. It is a copy of a message
that has already left the system, not an audit record, and nothing reads
it once the retries have ended. When the request asks for it:

```sql
DELETE FROM email_jobs WHERE lower(to_email) = lower('<EMAIL>');
```

### Technical logs — kept, scrubbed or left to rotation

`LOG_DIR/app.log` (10 MB, five backups — `app.core.logging`) and the
container stdout behind `docker compose logs backend` carry addresses and
client IPs: failed-login and lockout lines write the account's address and
the IP that tried it, the mail lines write the recipient. Erasure never
writes a log file.

**Handling:** before answering the request, remove the files
(`rm -f "$LOG_DIR"/app.log*`) and restart the backend, so a fresh file is
opened — the process keeps writing to the file it has open, and the five
rotation backups hold the old lines until they go too. Whether old stdout
still exists is the container runtime's log driver, not this application's
decision.

## Records the organization owns, and what to do with them

The equipment module lets an organization hand an asset to a person it has no
account for: `equipment_assignments.assigned_to_name` and `assigned_to_email`
are free text (`my_assets` matches a signed-in user to their assets by that
address). An attestation campaign sends each holder a link and keeps their name,
address, and — from the answer on the public page — IP address and browser
string in `audit_responses`. A partner (`partners`) can be a customer who is a
private person, an employee, or a supplier's named contact. These are the
organization's records, written by its members, and the application neither
exports nor scrubs them on request. The operator does it, in agreement with the
organization that owns them. On an instance with several organizations add
`AND organization_id = '<ORG_ID>'` to every query, so one organization's
records are not read or changed for another.

**Export** — match on the address, and on the name where a holder was typed in
without one (replace `<EMAIL>` and `<FULL NAME>`):

```sql
SELECT id, item_id, assigned_to_name, assigned_to_email, checked_out_at,
       expected_return_at, checked_in_at, checkout_notes, checkin_notes
FROM equipment_assignments
WHERE lower(assigned_to_email) = lower('<EMAIL>')
   OR lower(assigned_to_name) = lower('<FULL NAME>');

SELECT id, campaign_id, assignee_name, assignee_email, status, responded_at,
       dispute_reason, response_ip, response_user_agent, created_at
FROM audit_responses
WHERE lower(assignee_email) = lower('<EMAIL>')
   OR lower(assignee_name) = lower('<FULL NAME>');

SELECT id, name, type, is_consumer, email, phone, contact_person, address,
       tax_id, notes, created_at
FROM partners
WHERE lower(email) = lower('<EMAIL>')
   OR lower(name) = lower('<FULL NAME>')
   OR lower(contact_person) = lower('<FULL NAME>');

-- Hand-overs and journal entries that name the holder
SELECT id, item_id, action, changes, created_at
FROM item_history
WHERE action = 'CHECKOUT' AND lower(changes->>'assigned_to') = lower('<FULL NAME>');

SELECT id, action, target_type, target_id, snapshot, created_at
FROM audit_log
WHERE target_type IN ('equipment_assignment', 'partner')
  AND (lower(coalesce(snapshot->'before'->>'assigned_to', '')) = lower('<FULL NAME>')
    OR lower(coalesce(snapshot->'after'->>'assigned_to', '')) = lower('<FULL NAME>')
    OR lower(coalesce(snapshot->>'name', '')) = lower('<FULL NAME>'));
```

**Erasure** — decide with the organization what it must keep. An asset's
custody history is a record it may have a reason to retain; the contact data of
a person who asks to be forgotten usually is not. Where the request stands, a
scrub that keeps the rows and drops the identity, run after any asset still
held by the person has been checked in:

```sql
UPDATE equipment_assignments
SET assigned_to_name = 'Deleted holder', assigned_to_email = NULL,
    checkout_notes = NULL, checkin_notes = NULL
WHERE lower(assigned_to_email) = lower('<EMAIL>');

UPDATE audit_responses
SET assignee_name = 'Deleted holder', assignee_email = 'deleted@anonymized.invalid',
    response_ip = NULL, response_user_agent = NULL, dispute_reason = NULL,
    token_expires_at = now()
WHERE lower(assignee_email) = lower('<EMAIL>');
```

`token_expires_at = now()` closes the link the person was mailed. A `partners`
row is edited or deleted in the application itself, not by SQL. The holder's
name in `item_history` and `notifications` is history of what happened and
stays unless you decide otherwise; the journal entries found above cannot be
changed at all (next section). Say which of these stay in the answer to the
requester. Records that name the person only by name, never by address, are
found only by the name queries above; confirm each hit is the same person
before changing it.

## Record keeping

Log every handled request (date, type, user UUID, handler, completion
date) in the internal admin log. Do NOT store the requester's email in
that log after erasure is complete.
