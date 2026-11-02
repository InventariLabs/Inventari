# Equipment

## Job
"Know which physical thing is where, who has it right now, and when it next needs attention."

## Whose job
Whoever hands equipment out and takes it back — often the same person who fixes it. The statuses
and the moves between them are fixed, not configured; a viewer can look up where a thing went.

## Inside the boundary
One identifiable object followed through its life: what it is, its serial number, where it stands or
who holds it, what state it is in, and the dates that matter — purchase, warranty end, next maintenance. Retiring
it is a status change, recorded in its history, not a date.

## Outside the boundary
- Countable stock of interchangeable things → **Core — Inventory**
- The places → **Core — Spaces**
- Buying it → **purchase_orders**; receiving it → **warehouse**
- The people it is assigned to → **Core — Settings** (users)

## Own concepts / Borrowed
**Own:** everything about an asset's lifecycle — status, assignment, custody history, service log,
warranty and service dates, attachments, audit campaigns. Assignments, the service log,
attachments and campaigns are this module's tables; status, purchase date and warranty end are kept
on the Core record, under the item's `equipment` metadata, and the next maintenance date is kept in
the service log.
**Borrowed:** Item and its `serial_number` (a grandfathered Core column), StorageLocation, User.

## Deliberately not done
- **No finance.** Not an asset register for accounting: no ledgers, no postings. Depreciation and
  book value are indicative, straight-line, and shown only for an asset with a purchase price and a
  purchase date. The useful life is the asset's own, else its category's default, else the
  module setting, else five years.
- **No helpdesk.** A fault is a status here, not a ticket with a conversation attached.
- **No software or licence management.** A licence is not a physical thing.
- **No network discovery.** Nothing scans, no agent reports in, nothing is found by itself — every record is
  put there by a person.

## Switched off
The underlying items stay in the data, countable and locatable, but with no lifecycle: no
assignment, no status, no service dates. Inventory's product list shows them only while **Module
data in general lists** (Settings → General) is on — and it is off by default, with equipment on or
off, so switching the module off hides nothing that was shown. Nothing outside this module may present those as if they
were still being tracked.
