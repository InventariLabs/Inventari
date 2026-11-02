# Webhooks

## Job
"Tell the other system, as it happens, that something changed here — so nobody has to keep asking."

## Whose job
Whoever wired the two systems together, usually once. Nobody watches this module day to day; they
open it when something downstream stopped arriving.

## Inside the boundary
The endpoints to call, which events each subscribes to, the signature that proves the call came from
here (sent only for an endpoint that has a secret), and the record of what was delivered, what
failed, and when the module gave up on an endpoint. A failed delivery is retried up to the endpoint's
retry count (3 by default, 10 at most), backing off from 10 seconds; the Test button sends a sample
and counts toward the same failure tally. Two settings: how long delivery logs are kept (30 days by
default), and how many failures in a row switch an endpoint off (10 by default, 3 to 100). Addresses
are checked when they are saved. An endpoint the module has switched off can be reactivated by hand.

## Outside the boundary
- What an event means and when it is emitted → the module that emits it, via the typed event
  contract
- Being asked for data rather than sending it → **api_keys**
- Reaching a person → the notification subsystem

## Own concepts / Borrowed
**Own:** endpoint, subscription, delivery attempt, the circuit breaker's state.
**Borrowed:** the event catalog. Webhooks never invents an event; it forwards ones that already
exist.

## Deliberately not done
- **Outbound only.** Nothing is received here. An inbound integration is an API key and an endpoint.
- **No payload templating.** The payload is the typed event, so that a consumer can rely on it.
- **No retrying forever.** An endpoint that keeps failing is cut off and said to be cut off, because
  a silent queue growing behind the scenes is worse than a stopped one.

## Switched off
Nothing inside the workspace changes; the outside world simply stops hearing. Whatever was
listening must be able to tell that from an endpoint that is merely quiet.

Both halves of "stops hearing" are the module's own work, done without a person present:
matching an event to endpoints, and the retry worker. Neither asked whether the organization
still had the module, so switching it off took away the panel and left the sending — data
leaving for an address the admin could no longer see, signed with an HMAC the receiver reads as
proof of origin, with no way left in the application to stop it. Both ask now.

Endpoints are kept, not deleted. Switching back on resumes sending to the same addresses, which
is why the store says so before it happens. The module store asks before the module is switched
off, and before it is switched on when saved endpoints would start receiving again; switching it
back on is the only way to undo a switch-off.
