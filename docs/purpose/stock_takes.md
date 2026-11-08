# Stock Takes

## Job
"Walk the shelves, write down what is really there, and let the system settle the difference."

## Whose job
Whoever counts — often two people, often on a phone, often over more than one sitting — and the
same people finalise the session. Accepting a difference larger than the organization's tolerance,
or a count far above what the system expected, takes the approve permission, a manager's by default.

## Inside the boundary
A counting session scoped to some part of the location tree: what the system expected, what the
counter actually found, the difference between them, and the moment that difference is turned into
real stock movements.

Also inside: a session on a location covers the products in every location below it, and an active
count of a shelf or rack blocks an overlapping one. A difference beyond the session's tolerance (a
percentage set on the session) needs a reason, and is applied only once somebody with the approve
permission accepts it; a counted quantity above five times the system quantity is held back the same
way. A line the system holds nothing of has no five-times limit, by intent: there is no figure to
take a multiple of. With a tolerance set, any count on it is a difference beyond the tolerance and
waits for the approval all the same; without one it posts as counted, whatever the number. A
location that holds stock comes up in To do again once a number of days has passed since its last
count (setting `count_every_days`, 0 for off). Cycle-count schedules (daily, weekly, monthly or
quarterly; all stock, one location tree or one category; optionally a sample size and a tolerance)
are made through the API; a due schedule appears in To do and is started from there. Nothing runs
them on a timer. Purging a product that appears on a count line is refused while the module is on.

## Outside the boundary
- The stock figure itself, before and after → **Core — Inventory**
- The places being counted → **Core — Spaces**
- A numbered record of the correction → **warehouse**, which, while switched on, files the count's
  differences as one completed adjustment that moves nothing itself

## Own concepts / Borrowed
**Own:** StockTake, take line, counted quantity, the reason for a difference, session status,
cycle-count schedule.
**Borrowed:** Item, ProductTemplate, UoM (Inventory); StorageLocation (Spaces).

## Deliberately not done
- **No investigation.** A difference may carry a reason from a fixed list — damage, expired, loss,
  miscount, wrong location, wrong unit, system error or other — and "other" requires a note. Finding
  out who or what caused it stays a human matter.
- **No cost treatment.** A discrepancy is a stock movement, not a write-off with a value attached.
- **No auditor's sign-off, no certification.** This is a count, not an attestation.

## Switched off
Stock stands as it is. Nothing else depends on a session existing; any screen offering to "start a
count" must disappear rather than fail.
