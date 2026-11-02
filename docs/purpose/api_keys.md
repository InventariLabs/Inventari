# API Keys

## Job
"Let a script, or the automation in my house, talk to this workspace without me handing it my
password."

## Whose job
The person whose key it is. An administrator can see that keys exist and revoke them, because a key
that outlives its owner is the point of failure.

Revoking one is only worth something if what it did can still be read afterwards, so the journal
carries the key's prefix on every entry a request authenticated with it wrote — the key leaves the
list, the entries keep naming it.

## Inside the boundary
Issuing a token, showing it exactly once, naming it so somebody remembers what it was for, seeing
when it was last used, and revoking it. What a key may do is decided on the key itself: its
permission list is chosen when it is issued, from what the person issuing it holds, and the server
enforces that list on every request. A new key starts read-only — a dashboard or a home automation
only looks — and a write permission is a tick somebody puts there on purpose. A key can also be
issued for one scope a module has registered — today `printing`, for a print agent — and then it
carries only the permissions that scope is bound to and reaches only the endpoints that guard one
of those permissions, not whole paths. Some permissions no key ever holds: administering the
organization, its members, its settings, the installation's configuration and admin access. The
key register itself sits behind the settings permission, so no key reaches it either.

## Outside the boundary
- Whose actions the key's work is recorded as → the account it belongs to; its roles do not widen
  or narrow what the key may do
- The API it is used against → every module's own endpoints
- Being told that something happened, rather than asking → **webhooks**

## Own concepts / Borrowed
**Own:** the key, its name, its last use, its revocation.
**Borrowed:** the account the key acts as, and the scopes modules register.

## Deliberately not done
- **No more than the issuer holds.** A key is issued from what its creator holds, so a key can never
  be a way round one's own permissions. Existing keys kept the set they had when per-key lists were
  introduced; only a newly issued key starts read-only.
- **No administration through a key.** Deleting products, organization settings, AI connections and
  the key register itself stay with a person signed in.
- **No third-party app consent.** This is not OAuth; nobody grants anybody anything.
- **No shared keys.** A key belongs to one account, so that revoking it has a knowable consequence.

## Switched off
Existing keys stop working. That is a visible outage in whatever was using them, so anything
depending on a key must fail loudly, not quietly stop.

Which means the switch has to reach the authentication path, not only the screens. It did not:
the gate hung on the router, so switching the module off took away the screen for managing keys
and left every issued key authenticating. An admin who suspected a leak reached for the largest
lever they could see and ended up unable to view the key, unable to revoke it, and unable to
stop it — with the way back to control running through switching the module *on* again, which
nothing said.

The alternative was to refuse the switch while a live key exists. Rejected: it leaves that admin
with no lever at all, and it is the opposite of what removing an app does anywhere else.

So switching off **suspends**: the gate sits on the authentication path, every key answers 401
while the module is off, and the store asks first and says what will stop. Suspension is not
revocation, and the difference matters to exactly the reader this section opened with. The key
rows are untouched, and switching the module back on brings every suspended key back to life —
without an event naming the return. The way to take a key away for good is revoking it: a
revoked key stays dead whatever the module does afterwards.
