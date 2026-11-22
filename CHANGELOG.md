# Changelog

All notable changes to Inventari are documented in this file. Releases are
published as tags and [GitHub Releases](https://github.com/InventariLabs/Inventari/releases)
of the public repository; a release's notes are its section below.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/). A version
heading carries the date it was cut. The history starts at 0.11.0, the first
public release: the versions before it were never published, so its section
says what the release does rather than what changed since them.

## Unreleased

### Added

- A place for a site of your own beside the application on the production
  server. Every `*.caddy` file in `caddy-extra/` (or the directory
  `CADDY_EXTRA_DIR` names) is read as part of the Caddyfile, so a website on
  the main domain can be served by the same Caddy while the application runs on
  a subdomain, and survives updates, which an addition in a second compose file
  would not. The directory ships empty and a stack that does not use it is
  configured as before.
- A place for a delivery cost that reached no product. Freight that arrives
  after a receipt is posted can no longer be added to the goods, and the
  refusal now offers a way forward: on a posted receipt the **Costs that
  reached no product** section records the amount with a reason, the cost kind
  and the day it belongs to. The amounts are listed and added up per currency
  on a screen of their own, reached from the office panel in History, and each
  one can be removed again. They are never part of a stock value: *Stock on a
  date* and *Value movement* do not move when one is recorded, and there is no
  counter-account or double entry behind them. A currency other than the
  document's is refused, as it is for a cost added before posting.
- A statement of what the stock was worth over a period. **Value movement**,
  reached from *Stock on a date*, takes a first and a last day and gives the
  value when the period opened, what came in (bought, and produced or returned
  to stock), what was used, what was thrown away, what was dispatched against a
  document, every other way stock left, and the value when it closed. The opening and the closing are the figures
  *Stock on a date* gives for the evening before the first day and for the last
  one, and the lines add up to the cent; where the two ends differ by something
  the cost history does not account for (a cost added to a receipt after it
  arrived, a rounding cent) the statement says so on a line of its own. It
  downloads as a spreadsheet, an organization that keeps no cost history gets
  an explanation rather than a page of zeros, and where the profile hides the
  value of the stock the screen and the file hide it too. It is a statement over the
  cost history, not a ledger: no chart of accounts, no double entry, no closing
  of periods.
- Putting a print layout back as the built-in it came from. A copy of a
  built-in print layout on the Document templates screen that no longer
  matches it now carries a **Changed from the built-in** badge and a **Reset
  to built-in** action. After a confirmation that says everything changed in
  the template is lost, the copy's body is replaced in place — it keeps its
  name and whether it prints by default. A template written from scratch is
  neither marked nor offered the action.
- Planning several production runs at once. A planned run no longer reads the
  shelf as if it were the only one on it: the draft runs are counted one after
  another, by planned day and then by creation, so two runs that each fit on
  the shelf are not both shown as covered — the run list and a run's page say
  **covered**, **partly covered** or **short**. A new **Plan** screen in
  Production shows the planned runs of a week or a month by day (a list by day
  on a phone), moves a run to another day, and lists everything those runs need
  in one place: in stock, on order in open purchase orders with their expected
  dates (the column is absent while purchasing is off), and still missing.
  **Order what is missing** raises one draft purchase order per supplier and
  currency from each ingredient's best price in the supplier's own unit (offers
  in your own currency first, never compared with another currency by their
  numbers, and a volume price the shortage does not reach is not bought unless
  the whole order costs less), sends ingredients
  with no supplier to the shopping list, and proposes an ingredient that has a
  recipe of its own as a planned run instead of a purchase. A run that uses
  such an ingredient counts on what the shelf holds of it and on runs of it
  planned for its day or earlier — never on a run planned after it — and the
  run list and the needs list say the same about it. What is on order or
  planned is spent once: a delivery ordered for one week, or a run planned for
  it, is not counted again by a later one. A product you make that falls below
  its reorder minimum is now proposed as a production run, in To do and in the
  reorder alerts, and no longer as a purchase.

- A production run can be started, filled in portions and finished on
  different days, for wine, cheese, beer, ferments and anything else that
  matures. **Start run** takes the ingredients off the records on the day you
  name and leaves the run *In progress* (in the list, on its page and in To
  do); **Add portion** puts part of the output on the shelf with its own day and
  batch; the BOM's process steps are ticked with the day each was done; **Finish
  run** closes it on a later day at the quantity the whole run made, and its
  unit cost divides what the start took by what came out. Cancelling a run in
  progress gives the ingredients back to the batches they came from. A run
  filled in portions can end up with several batches: its page and its batch
  record name them all, each has its own labels to print, and a hold or a
  release acts on every one. As when a run is completed in one step, **Start
  run** lets you choose which batch of each ingredient the run takes, and a
  portion and the finish take the best-before you give them (the day made plus
  the product's shelf life when you leave it empty). What a started run took is counted as work in progress in
  the stock value and in the as-of valuation (`work_in_progress_value`), so the
  warehouse does not look poorer between start and finish. New endpoints: `POST
  /maker/production/orders/{id}/start`, `/portions` and `/finish`, and `PUT
  .../steps/{index}`; modules that report a stock value can register a reader
  with `register_work_in_progress_provider`. For module authors, the valuation
  API also gains `add_value_to_layer_async` (a cost that arrives after the
  receipt, once per layer and dated from the day it is added, so an as-of
  report about an earlier instant reads what it did then), a `record_receipt_async`
  that answers the layer it opened, and `unpriced_stays_unknown` for a caller
  that will state the cost itself later instead of borrowing the older stock's
  rate.
- A BOM line can be marked **Always make fresh**: an ingredient that has a BOM
  of its own is then made through it every time and never taken from stock.

- The MCP Server module serves the Model Context Protocol over Streamable HTTP
  at `/api/v1/mcp-server/mcp`, authenticated with an API key that holds
  `mcp_server:use` and acts only in the key's organization. Seven read tools
  and two resources answer from the same CoreAPI calls the screens use, so the
  stock number and the tenant scope stay in one place. Two guarded write tools
  complete the loop: `create_item` opens a record through the create service,
  and `correct_stock` sets a counted quantity through the stock posting rules —
  a locked group, one write that posts the movement and the cost layer, the
  register's copy when Warehouse is on, and a required reason in the record's
  history and the organization journal. Both need `items:write`, and the
  module's README carries a Claude Code quickstart. The key travels in
  `X-API-Key`, which the endpoint and the rest of the API both accept; an
  organization lists the hosts and origins its deployment answers on in the
  module's settings card, and every other `Host`/`Origin` is refused.
- On the public demo a visitor can connect an AI agent to their own sandbox.
  Every sandbox the demo hands out has API Keys and MCP Server switched on and
  the demo's address allowed, so a visitor issues a key there — read-only, or
  with **Add products and change stock levels** — and the agent searches a
  product, reads its stock and posts a correction in that sandbox alone. The
  demo publishes no key; the nightly rebuild deletes every key with its
  sandbox. `docs/DEMO.md`, *Connect an AI agent*, walks it in about ten
  minutes and says what an agent may do there, the limits it meets and that
  what it reads goes to the model provider the visitor chose.
- A module can close what it opened: `BaseModule.on_shutdown_async` runs at
  application shutdown in the reverse of the startup order, so a task group,
  connection or exit stack started by the module is closed with the app, and
  `define_module(on_shutdown_async_hook=)` wires it. `app.core.module_sdk`
  exports `get_current_user`, `audit_actor_scope` and `current_actor` for a
  module that authenticates its own ASGI transport or names its actor in the
  journal, and `effective_expiry`, the day a package really stops being fit to
  use — the batch's date or the use-by an opening wrote, whichever is earlier —
  so a module reading an expiry window can judge a package by the date the
  screens and the forecast report, which is also the date the items list's
  `expiring_days` filter selects on.
  `core_api.items.list_by_expiry_async` takes `expiry_after` and
  `expiry_before`, so a caller reading one expiry window filters the query
  instead of reading a capped list and discarding rows after it. The app-level
  default rate limit now keys a plain Starlette route as it does a FastAPI
  endpoint, so a transport served that way is counted per API key.
- A new community module package can be handed to an AI coding agent.
  `module new-community` now writes an `AGENTS.md` into the package — what a
  module may import, the five maintained languages, migrations the package
  owns, the purpose card, tests and the command that checks the package before
  install, with links to the full guides at the platform's version — and a
  `CLAUDE.md` that points at it. MODULE_QUICKSTART.md has a section on
  building a module with an agent: what to give it, which checks refuse its
  mistakes and how to check the result before installing it.
- The audit journal (`GET /audit-log`) counts at most ten thousand entries on
  its first page, as the product, stock and movement lists do: past that,
  `total` is where the count stopped and `total_capped` is true, and the
  settings screen's pager says "more than 10000". The cursor carries both to
  the later pages.
- `core_api.audit_log.list_for_org_async` takes `count_up_to`, which stops the
  count one entry past it, the way `core_api.stock_moves.list_rows_for_org_async`
  already does.
- `make new-module` writes an empty `moduleApi.ts` into the new frontend
  module: the one file `check:boundaries` lets another module import from it,
  so the first module that depends on it adds a name there instead of
  importing the module's internals. The dead-code check reads every module's
  `moduleApi.ts` as published surface, and no longer reports a name in it that
  nothing in this repository imports.
- A production formula costs out on the day it is written. An ingredient with
  no stock and no supplier quote can be given a price per unit on its card;
  the price belongs to the product and every estimate asks it after the cost
  layers and the supplier quotes. Each process step carries how long it takes,
  production settings carry an hourly rate for the organization's own work,
  and the formula's labour is its steps' time at that rate — shown as a
  computed line beside the fixed costs, and included in the estimate, the
  preview and a run's actual cost. A completed run keeps the formula's answer
  beside what it cost, and each ingredient says whether the difference came
  from a price or from a quantity. A formula whose ingredients the records do
  not hold says so at the top of its page, and from there the stock can be
  entered (quantity and price) or ordered as a draft purchase order when
  purchasing is on.
- A batch's trace for a recall: from a batch, the receipts that brought it in
  and the deliveries that sent it out, each with its partner, address, date and
  quantity — one step back and one step forward, as food law asks. A production
  run can name the batch its output goes into, and the trace follows it on to
  that batch and its own customers. The trace exports as a spreadsheet to hand
  to an inspector.
- A production run files its output under a dated batch. A run nobody named a
  batch for names its own from its day and a counter, unique among the
  product's batches. The batch carries the day the run was made and a
  best-before of that day plus the product's shelf life — set in days on the
  card of a product that has a BOM — which the person closing the run may
  change; the stock it puts away carries the same date, so the expiry lists,
  To do and the earliest-date-first order treat made goods like received ones.
  Before a run closes, its screen shows which batch each ingredient will be
  taken from and lets the person pick another from a list or by scanning its
  label; the run then takes exactly those batches. A finished run prints
  labels for its batch — the product, the batch code in bars, the production
  date and the best-before, one per unit made — opens a one-page batch record
  that prints on A4 and reads on a phone, puts the batch on hold and releases
  it, and keeps photos and files filed under it. At home the run speaks of
  jars and a best-before date and never asks for a batch code. The printing
  module draws batch labels (`lot_ids`, `POST /printing/lot-labels/png`, up to
  two hundred copies), and the module SDK exports the upload policy a module
  checks its own attachments with.
- Every page names its browser tab, bookmark and history entry, in the
  language on screen: `Products · Inventari` instead of `Inventari` for all of
  them, and the title follows the page on every navigation. A screen reader
  announces it when the page changes. The sign-in, registration, password
  reset, privacy, invitation, set-up and attestation screens have titles of
  their own.
- A made product's ingredient list, allergens and nutrition come from its BOM
  and go on its label. A product's card carries, with Production on, the name
  it goes under in an ingredient list (a legal food name, or an INCI name for a
  cosmetic), the 14 EU allergens and a may-contain list; what the product's
  name suggests is offered for a person to confirm, and nothing counts as an
  allergen until someone has. A BOM's new **Label** tab writes the ingredient
  list heaviest first as used (a line's loss included; equal weights by name),
  a made ingredient with its own ingredients in brackets and the allergens in
  bold; it collects every allergen of every level with the ingredients that
  bring it (one declared on the product itself is kept), lists what the product
  may contain and does not already, names what nobody has checked for allergens
  and what nothing says the weight of, and gives the nutrition declaration per
  100 g of what the batch yields — energy, fat, saturates, carbohydrate, sugars,
  protein, salt — leaving a figure unknown and naming the ingredient that lacks
  it rather than counting it as zero. A made product's card names its default
  BOM and shows that BOM's allergens, each with what brings it. The product
  label and the batch label can print the list and the allergens
  (`composition` on `POST /printing/product-labels/png`, `/lot-labels/png` and
  print jobs) no smaller than the 0.9 mm letter the regulation allows on a
  small package, and refuse a label too small for them; a batch's label reads
  the BOM its run used, not the product's default. Every screen says the result is computed
  and the producer's to check. A product's nutrition figures gain saturates.
  New endpoints: `GET/PUT /maker/labelling/products/{template_id}` and
  `GET /maker/labelling/recipes/{recipe_id}`; the module SDK exports
  `pick_by_lang`.
- For module authors: `core_api.items.update_async` takes an optional `bulk`
  flag that marks the edit's journal entry as one of a batch, and
  `core_api.ai_connections.set_binding_async` an optional `user` it names in
  the entry it writes. Callers that pass neither are unchanged.
- For module authors: the module SDK exports `read_sheet` and `cell_text` —
  the shared reader that turns an uploaded CSV or workbook into a frame of
  text cells (tolerant of a BOM, of the locale's codepage and of semicolon or
  tab separators) and the accessor that reads one cell as the text it is.
- Closing a month says what it would leave behind. The **Close this period**
  dialog counts the documents dated in the month that are still drafts, waiting
  for approval, or confirmed and not completed, and links to the first of them,
  because once the month is locked none of them can be confirmed, completed or
  changed. The date picker of a document marks the days of a closed month as
  unavailable and says why.
- The person who sent a document for approval is told when it is approved, with
  the approver's note, as they already were when it was rejected. The people
  picker of a workflow stage marks the members who cannot see approvals, since
  naming only such people is refused when the stage is saved.

### Changed

- Settings → **My modules** is now **Organization modules** (**Moduły organizacji**
  and so on in the other languages): every choice on it switches modules on or off
  for the whole organization, which the old name did not say. The confirmation for
  a workspace mode now lists the settings it resets and no longer promises that
  switching back restores them.
- Mail an organization sends goes out under the organization's name when no sender
  name is set in **Settings → Email**, as its invitations and documents already
  name it. A sender name chosen there is kept.
- The audit log words the removal of a role, a webhook channel or an AI connection
  as **Removed**, and its subtitle lists every verb the log shows.
- Rows that have finished their work no longer stay for ever. Once a day an
  instance deletes outbox events published more than 7 days ago, sent and failed
  mail queued more than 120 days ago, read notifications older than 90 days and
  unread ones older than a year, so the list of mail that never arrived now goes
  back 120 days. An administrator changes the windows with
  `EVENT_OUTBOX_RETENTION_DAYS`, `EMAIL_JOB_RETENTION_DAYS`,
  `NOTIFICATION_READ_RETENTION_DAYS` and `NOTIFICATION_UNREAD_RETENTION_DAYS`.
  Sent mail drops its attachment as soon as it has left. The first run on an
  older instance can take a while and works through the backlog in batches.
- AI costs are stored as exact numbers, so the totals on the administration
  screens add up to the cent. The upgrade rewrites `ai_usage_logs` and blocks
  that table while it does; a stored cost that was not a usable number (not a
  number, infinite, or a million dollars or more for one call) becomes unknown.
- An ingredient that has a BOM of its own is now taken from its own stock first,
  and only the part that stock does not cover is made through its BOM — the
  dough made yesterday is used before flour is taken again. The availability
  check, the preview and cost estimate, the shortage list, the shopping and
  purchase suggestions, the multi-level view and the run itself agree on that
  split. Existing lines take stock first after the upgrade; mark a line
  **Always make fresh** to keep the earlier behaviour of making it every time.
- **Breaking:** a production formula's `process_steps` are objects
  (`{text, minutes}`) rather than bare sentences, so a step can carry its
  duration. Writers may still send plain strings, which are stored as steps
  with no duration; a reader of `GET /maker/recipes/{id}` or of the catalogue
  must read `step.text` instead of the string itself. Steps stored by an
  earlier version are rewritten by the module's upgrade: a sentence becomes a
  step with no duration, so nothing has to be re-entered.
- The frontend's exception registers no longer fail `make check-frontend` and
  CI on a calendar day. In `frontend/scripts/integration-only.json` (API
  routes with no screen), `frontend/scripts/suppressions.json` (silenced
  frontend findings) and `frontend/scripts/invalidation-keys-baseline.json`
  (query keys outside `hooks/queries/keys.ts`), an exception that is right by
  design carries no date, and a date that has passed on one that waits for a
  fix prints a warning and refuses nothing. An entry names its `verdict`: a
  module author recording an API-only route writes
  `"verdict": "integration-only"` with a reason and an owner, and no
  `expires`, and a query-key entry is `by-design` or `to-fold`, the latter
  with an `expiry`.
- The issuer block of a printout reads as an address block: the tax ID carries
  its label (NIP: 1234563218 on a Polish printout) and an address in Polish,
  German, French, Spanish or Portuguese puts the postal code before the town
  (ul. Magazynowa 5, 90-001 Łódź). The subtitle of the period closure screen
  describes the screen instead of inviting an action that a read-only account
  cannot take.
- The line picker of a delivery, a scrap, a transfer or any other warehouse
  document now finds stock the way the catalogue picker does: by the product's
  name, brand, the code on the record or its product card, the label code and
  the serial number, not by name alone. A one- or two-character fragment
  matches only the start of a field, so typing `oi` no longer lists
  `Olive oil` while `Ol` still finds it; a search term of three characters or
  more still matches anywhere in a field.

### Fixed

- A production run closed far above its plan asks first. **Finish run** and
  **Complete run** name the extra quantity once the figure is more than a
  quarter above the plan, say that the ingredients stay as planned, and keep
  the button disabled until the box for that very quantity is ticked; typing
  another number asks again, and a dialog opened afresh starts with an empty
  quantity. The recipe catalogue marks a unit cost that comes from a run which
  made more than it planned, as the cost is spread over output the ingredients
  did not grow with (in the list view the note wraps inside its column), and
  the month's margin says how many of its runs closed above plan. The API
  gains `last_run_overproduced` on the recipe catalogue item and
  `overproduced_orders` on the monthly result.
- A receipt posted against a purchase order names the order. The receipt's
  page shows it under **Purchase order**, linked to the order, and both
  built-in print layouts print its number, so whoever holds the receipt later
  can reach the order it was received against. A receipt made from the
  order's own page, which keeps the order number as its reference, does not
  show or print it twice. Print templates can use `source_order_number` and
  `printed_reference`.
- Refusing to issue more than the shelf holds states the figures the right
  way round: with 8 on the shelf and 99 asked it reads "8 of 99 available,
  91 missing" instead of "8 of 99 could not be reserved", which named what
  was there as what was not.
- On a phone, **The rest did not come — finish** pressed before anything was
  counted no longer posts an empty receipt reading "Received 0 lines. The
  goods are in stock". Nothing is posted, the receipt stays open for the
  goods still expected, and the screen says that nothing was received.
- Starting phone receiving for the rest of an order no longer warns that the
  order already has an open receipt when the receipt it names is the one the
  start is making, or holds nothing the order still owes (a correction, or a
  draft for a product the order no longer expects).
- An adjustment posted by a stock take and an issue registered by a recipe's
  cooking name their source in words ("Stock take", "Recipe production") on
  their page and in the register instead of an internal reference and id; on
  the page each links to the stock take's report or the recipe while that
  module is on. A recipe's issue now refers to the recipe, and its note no
  longer carries the picking session's id.
- The audit log records the backorder a short receipt drafts, naming the
  receipt it continues; a task assignment names the document or the task and
  the person instead of a raw kind and an id; and a new partner's type reads
  in words ("Supplier") instead of `SUPPLIER`.
- The phone receiving card no longer says "Expected 1 pcs." for a product
  nobody expected — one added beside an order or scanned on a receipt with
  none — nor "fewer than expected" when its count is lowered.
- A member who may write documents but not manage them is told what they
  cannot do: their own draft correction says only a manager can delete it,
  and a confirmed document says why **Cancel document** is disabled, in a line
  a phone shows rather than only in a tooltip.
- On a phone, tapping an order's delivery on **To do** no longer makes it the
  reader's before anything has begun; it becomes theirs when its receiving
  starts.
- Scan document offers the torch only on a camera that has one, and the
  location wizard keeps a zone name typed on its first step when a zone chip
  is pressed afterwards.
- Small controls are easier to press on a phone. Checkboxes in the document
  register, the approval queue, Codes and labels and the list of ingredients
  without a product are pressed through a 44 px square, and text links and
  small icon buttons that stood 15 to 20 px tall — document links on Start,
  History, a document's page and a lot's page, the audit log's "Show the
  whole change" and record ids, "In every location", "Create role", "Open
  settings", the equipment form's "Manage" and "Create model" links, a tag's
  colour, a recipe's select and a collection's rename and delete — are at
  least 24 px.
- The first-contact and settings screens read the same everywhere: a sign-up link
  that a newer one replaced says so on arrival instead of asking for a password
  first; the validation bubbles a browser shows for a required or too-short field
  are worded in the app's language; the SMTP host error clears once a host is
  typed; the invitation email names the person who invited and calls the role by
  the same name as the join page; a network failure reads "Cannot reach the
  server" on every screen; the audit log hides its row count and pager when it
  could not load; entering one-module mode records each module it switches off;
  the unsaved-changes question agrees with every form name; **Settings → About**
  says which version its source and guide links belong to; the Partners
  permissions sit under Partners in a role's permission list; and **Privacy**
  offers the way back to the app to someone signed in.
- Smaller wording and clarity fixes found walking the app on a phone. A
  recipe's "Output in stock" figure now carries its unit. The warehouse
  start says "No document has been posted yet today" instead of claiming
  nothing moved when stock moved without a document. The Equipment launcher
  tile and overview count "warranties ending soon", as the window they
  count, and a purchase order's value on the list and on its page says it is
  gross, as the approval card says net. The product sheet opened from an
  attention row names the product in its header. Tapping a to-do task on a
  phone says the task is now yours and offers to give it back. The launcher
  tile is called "Browse Modules", like the page it opens, and the toast after
  Replenish names the shopping list it filled and opens it.
- A production run or batch record whose ingredients carried no purchase
  price no longer shows a cost of zero per unit beside a total that reads
  "—": the per-unit figure is "—" too until some rate is known, so an
  unknown cost is not mistaken for a product that costs nothing to make.
  `manage.py db doctor` also names the migrations still to be applied when it
  lists a column whose type differs from the models, so the notice on an
  upgrade start reads as expected, and *Updating* in `DEPLOYMENT.md` says how
  a development stack takes the backup and lists the variables a release
  added.
- Counting a location that has sub-locations now offers, in the bar of
  products outside the stock take, a product received onto a sub-location
  after the count started, as counting that sub-location itself does.
- A production recipe's reference price can no longer be negative. Creating
  or changing a recipe with one is refused with a message naming the field,
  instead of being stored and understating the result per unit of every run
  made after it; zero is still allowed.
- Saving a print layout whose template code does not parse or render — a
  purchase order, warehouse document or equipment layout — is refused, with
  the line and the complaint, instead of being stored and then breaking every
  printout made with it. A layout already stored in that state — a purchase
  order, a warehouse document, the file over several documents, a packing
  slip, a pick list or an equipment protocol — prints with the built-in
  layout rather than failing with "An error occurred".
- On a slow connection the Inventory and Equipment overviews no longer state
  something that is not true while they load. *My locations* shows placeholders
  instead of "No locations yet" and its create button, and the Equipment
  attention card shows no count ("8 assets need attention", later 9) until every
  list it adds up has arrived; the fleet by category and the recent check-outs
  wait for their answer the same way.
- A member whose role cannot read a module is now told so. A module screen
  opened without that module's read permission says the account cannot open
  it and whom to ask, instead of "Your account can read this module", and the
  product, purchase order, stock take and category lists show the refusal
  without a *Try again* button that could only be refused again. The role
  editor also warns, before a role is saved, about a granted module whose own
  read or whose required modules' reads (stock takes need products and
  locations) the role does not hold; the role can still be saved as it is.

- After a location is moved physically, **Movements** and a product's
  *Movements* tab show what happened before the move at the path the location
  had then, as the move dialog promises. Goods put on a shelf while it stood
  in one hall no longer read as having gone into the room it was carried to
  later. The rows the move itself writes name the moved location's whole path
  before and after, its own name last, instead of only the places it left and
  reached. A move that only corrects the layout still rewrites nothing: the
  stock was always where the corrected tree puts it.
- Archiving a location no longer moves the stock of the locations inside it.
  Those locations stay active, but their products were relocated to the chosen
  target and the shelf was left empty while the goods had not moved. Only what
  stands on the archived location itself is relocated, the archive dialog
  asks for a target only when that location holds products, and a location
  that holds nothing of its own archives without one.
- A BOM line's unit is read against the ingredient's stock unit, and a line
  that cannot be converted is refused instead of silently drawing the wrong
  number. A formula line reading "Wheat flour 300 g" on a product kept in
  pieces used to take 600 pieces for two batches and record "600 pcs"; the
  line is now refused when it is saved, naming both units, and a run refuses
  one already stored that way. The Composition tab marks such a line as a
  unit mismatch until a unit is set, and a line that does convert — 500 g
  against stock kept in kilograms — draws the converted amount and records
  it in the shelf's unit.
- Undoing a production run no longer changes what the stock is worth. The
  output leaves the books at the value its own run put in, instead of at the
  product's oldest cost layer, which can belong to an earlier run made at a
  different cost; each batch of a run filled in portions leaves at its own
  value too. Undoing a run used to leave every quantity back as it was while
  the total fell or rose by the difference between the two runs' costs.
- A recipe imported from JSON or from a web page now carries the allergens its
  ingredient names suggest, as one typed through **New recipe** does. An
  imported cheese omelette of eggs, butter and cheddar read "No allergens
  marked" on its page and in its export; the review screen now shows Eggs and
  Milk ticked for the cook to correct, and a line that names its own allergens
  keeps them. Recipes imported earlier get theirs when the instance is
  upgraded.
- *Stock on a date* and *Value movement* now cut a day where the organization
  lives, not at midnight UTC. A receipt booked at half past midnight local time
  used to sit in the opening value of its own day, the note about where the
  ledger starts named the wrong day, and a first-month organization saw only a
  refusal because the page opened on a period starting before its ledger. The
  statement now opens on the first day it can report when no first day is
  picked.
- The sale price calculator and the per-product cost estimate now count the
  formula's fixed costs and the labour its timed steps take, not only the
  ingredients. A batch that cost 25.28 a kilogram was priced from 11.28, so
  the suggested price sat below what the run cost; the calculator now lists
  the three parts under the total, and the production preview's total matches
  the per-unit figure beside it. The preview lists the fixed costs and labour
  under its ingredients, and each line's percentage and the cost-share chart
  are shares of that whole total.
- Counting a location that has sub-locations now tells two records of one
  product apart. The count cards and the scan chooser show the expiry of
  items standing on any depth below the counted location, so a scan no longer
  adds one to whichever of two identical rows is tapped. The completed report
  and its CSV export carry the same expiry and record number the counting
  screen shows.
- A fixed cost line of a production BOM can no longer be saved with a negative
  amount, which lowered the BOM's unit cost, the run preview and the cost of
  every run after it. The refusal appears beside the Amount field with what was
  typed kept; a line saved negative earlier still opens and can be corrected.
- Picking several documents from the list no longer ends in a dead end when
  one of them is already in a picking session. If the session is your own —
  opened on a phone and left — the dialog says so and offers **Continue that
  session** or **Discard scans**; if a colleague holds it, it offers to take
  it over, which opens that session at once, or discard their scans, as the
  document's own page already did.
  **Retry** now appears only after a server failure, never after a refusal
  that would only repeat itself.
- On a phone, the header's Back arrow on a screen opened by a direct link —
  a document opened from a link or a refreshed page, for one — no longer ends
  on a "Page Not Found" at `/warehouse/documents`. With nothing earlier in the
  history it climbs to the nearest screen above that exists, and to the home
  screen when there is none: from a document or History opened by a link that
  is the launcher, never the warehouse root that only sends you back, and from
  a location zone it is the locations list, never "Location not found".
- The Settings audit log shows the reason a workflow release left on the
  requests it closed in the reader's language ("Workflow deactivated",
  "Workflow deleted") instead of the raw English text.
- Importing rows into a document that is not saved yet, when the session has
  ended, no longer says "this was not saved" over an empty form: the import
  only reads the rows, so the message is the plain "your session has ended".
  A form that already holds something the reader typed, and an import that
  also creates products, keep the longer warning, because signing in again
  loses that work.

- When the session ends on a request that only reads (picking an import file,
  looking up a product) while a document form holds unsaved work, the reader
  is now told that what was entered was not kept, instead of landing on the
  sign-in page with nothing said. The document form also asks before the page
  is reloaded or left once something in it has been changed, and says nothing
  while an opened draft is untouched.

- The price a document suggests for a supplier's product is the price that
  line can get: valid today, from a quantity tier the line's quantity
  reaches, and in the organization's own currency before any other. It used
  to be the lowest number on the whole price list, so a 1000-piece price or
  an expired promotion was suggested for a line of five. A quote in another
  currency no longer fills the line's price, which the document would have
  kept under its own currency. The supplier price comparison lists the
  organization's currency first instead of sorting different currencies by
  their digits.
- The last purchase price a receipt suggests is what was last paid for the
  product. It was the price of whichever document came last, so a product
  bought at 8.00 and then delivered to a customer at 10.00 was offered at
  10.00 on the next receipt, and that price went on into the stock value.
  Only receipts and internal receipts count now; a delivery, a customer's
  return, a correction, a scrap or a transfer does not. A delivery form is
  offered the rate of tax alone: neither what was paid nor a supplier's
  offer is the price a customer is charged. `GET /api/v1/warehouse/price-hint`
  takes the document's type as `document_type` to tell the two apart.

- The first `make dev-up` on a machine that has no images yet no longer
  fails with a duplicate-type error from a module's migration. The backend's
  first start and the bootstrap's own `db upgrade` migrated the same empty
  database at the same time, the container restarted and the bootstrap
  stopped with `Error 137`; `manage.py db upgrade` now waits for the lock the
  backend takes while it migrates, so the two run one after the other.

- A completed or archived shopping list is a closed record and is no longer
  written to. It is no longer offered or preselected as the place for new
  items — the recipe card, the scan add, the product quick action, the
  inventory dashboard card and Replenish All all pick the newest active list
  — and adding to it from a recipe, or refreshing a meal plan's list so that a
  line of it asks for more, is refused with "Reactivate it first" instead of
  changing it. `GET /api/v1/shopping-lists` takes a `status` filter
  (`active`, `completed` or `archived`). The page of a completed or archived
  list now says so and offers **Reactivate** in place of Add, From recipes and
  the other changes, and the refusal names no status word, so it reads the
  same in every language.
- The cost analysis no longer counts a production run's product, or the
  ingredients put back when a run is undone, as money spent. They were added
  to the purchases they came from, so the same grapes were counted when
  bought and again as wine, and the waste percentage was measured against the
  inflated total. Total spent, the monthly trend and the weekly spending
  behind the forecast now add up only what came in from outside. Receipts
  posted before this release cannot be told apart and keep counting.
- Purchase patterns no longer read a production run's product as a purchase
  of it. Two runs of a wine used to list the wine as bought twice, at the
  run's cost; the report now leaves out records a run made. Records made
  before this release cannot be told apart and keep counting.

- The public attestation page declares the language it is written in
  (`<html lang>`), as the rest of the application does, so a screen reader
  pronounces a Polish page in Polish. Choosing a language before signing in no
  longer tries to save it to an account that does not exist, and no longer logs
  an error in the console; the choice is still kept for the next sign-in.
- The locations list and the location tree answer within their screens'
  budget in a large warehouse. A page holding a warehouse or the containers
  above its shelves, and the first levels of the tree, count every record
  below them, and the filter that leaves out a module's records made the
  database visit those records one by one: at a hundred thousand products
  such a page took 0.6 to 0.8 s at the 95th percentile, and now takes about
  0.2 s, with the same numbers on every screen that prints them.
- A server worker no longer stalls for two or three hundred milliseconds now
  and then while Python's garbage collector walks everything the application
  built at startup. Those objects live as long as the worker and are now left
  out of collection once startup is done, which took the slow tail off the
  reads that allocate most, the location tree among them.
- Deleting a recipe collection now leaves a row in the audit journal, as
  deleting a recipe or a meal plan does. The row names the collection, who
  deleted it and any sub-collections that went with it, and appears in the
  journal's filter as "Recipe collection". Renaming or filing recipes under a
  collection still writes nothing.
- The recipe list's Next page button shows the next page. With more than
  fifty recipes the page asked the server for the page start under a name it
  does not read, so page 2 showed page 1 again; it now sends `offset`.
- The registration form from an invitation keeps the address typed into it.
  The invited address used to fill the field whenever the invitation check
  answered, so an address typed before a slow answer was replaced without a
  word; the field now takes the invited address only while it is empty.
- On a phone, the camera of the document and purchase-order line editors opens
  in view. With the Scan switch near the bottom of the form, the camera used to
  open below the edge of the screen, where nothing seemed to happen, and a
  phone's browser may not start a video it cannot see, so no code was read
  until the worker scrolled; the form now brings the switch to the top, with
  the camera right under it.
- The dead-end notice on an approval request no longer blames the requester for
  the stage's dead end. A stage listing them beside people who cannot see
  approvals names only those people, and the access step names only them; an
  administrator is offered the self-approval setting as another way out. The
  notification sent for the same case no longer calls a stage naming several
  people "the person".
- A requirement scaled by a ratio that does not divide evenly no longer asks
  for one unit more than it needs: five servings of a three-serving recipe
  that asks for three eggs now ask for five eggs, and planning five of a
  production recipe that yields three lists five pieces, not six. The
  production preview's to-buy figure and the line the shortfall writes agree
  on the quantity, and the add-item dialog of a shopping list writes its
  quantity ceiling in the reader's decimal mark.

- The stock aging of a product with more than a thousand receipts
  (`core_api.stock_moves.aggregate_aging_buckets_async` and
  `list_receipts_for_aging_async`) counts the stock still on the shelf. The
  receipts were cut at a thousand, oldest first, before what left was netted
  off them, so the newest stock, the part still on the shelf, dropped out of
  the buckets.
- Recipe picking no longer offers a sealed pack lighter than the card's full
  pack as the open one to cook from: a pack is open when opening it marked it
  so, which is what the picking order and the candidate list already went by.
- Two deletions of shelves, batches, partners or users that had stock
  movements over the same products can no longer deadlock on the ledger's
  per-shelf totals: the database now takes those rows in one order whether a
  movement is added or taken away.
- The core API reference (`docs/subsystems/CORE_API.md`) labels each method
  READ or WRITE by what it does, as the method declares it, instead of by
  words in its name; about two dozen methods were labelled the wrong way
  round. Summaries no longer stop mid-sentence, and types and enum defaults
  print as a caller writes them.
- An uploaded picture is measured before it is decoded. The ten-megabyte
  limit bounded the file, not what it decodes to: a PNG of a few hundred
  kilobytes can describe a 12000 × 12000 canvas, which took close to 570 MB
  of server memory as an item's or a recipe's cover, or as a photograph for
  Vision AI to read. A picture of more than 60 million pixels — more than a
  50-megapixel phone photograph — is now refused as unreadable on all three
  before any of it is decoded. The browser already shrinks what it uploads,
  so the limit is met by API clients and by recipe covers fetched from other
  sites. A photograph Vision AI cannot read at all is refused with "This file
  could not be read as an image" instead of an internal error.
- The audit journal now records acts it used to miss. Saving the SKU naming
  schema, binding an AI purpose to a connection, and adding, editing or
  removing an AI connection each leave an entry (the key itself is never
  written down); a module that writes its own settings through
  `core_api.settings.set_bulk_async` leaves the same entry as the settings
  screen does. A holder who confirms or reports an asset from the attestation
  link leaves an entry naming the holder. An organization founded by a
  self-registration starts its journal with the entry that created it. A bulk
  retire that closes an asset's open checkout records the handover back, and a
  bulk location move is marked as one of a batch like the other batch edits.
- Clearing the purchased lines of a shopping list keeps what was bought in the
  list's purchase history, as archiving the list already did.
- A location an asset is checked out to can no longer be deleted out from
  under the checkout. The delete guard counted only the records whose home the
  location is, so a place an asset stood in answered 204 and left the open
  checkout naming a location that no longer existed, while the Equipment
  Locations row offered Delete over a place it counted an asset in. The row
  and the server now count every record that names the location — the home it
  belongs to, or the place it is checked out to — and both doors into a delete
  (the single delete and the reorganization) refuse it.
- A place that equipment was ever checked out to can no longer be deleted.
  Deleting it blanked the holder line of that past checkout in the asset's
  history: the dates stayed, the place the card named was gone. The delete is
  now refused with a message that points to archiving the place instead, as a
  place with stock movements already was.
- The ingredient dictionary reads the CSV a spreadsheet actually saves. A
  file separated by semicolons — the separator in Polish, German, French and
  Spanish locales — imports its rows instead of being refused as unreadable,
  a file saved in the local codepage (cp1250) keeps its Polish letters
  instead of storing a replacement character for each one, and a decimal
  comma such as `368,5` reads as the decimal it names.
- A shopping exclusion made only of spaces, zero-width spaces or a byte order
  mark is refused instead of being saved as an empty name that excludes
  nothing, and the next such name no longer answers that the exclusion
  already exists.
- The ingredient dictionary refuses a name made only of invisible characters
  (a zero-width space, a byte order mark) instead of filing it under the empty
  key every blank row shares, and counts such a row as an error on import. A
  CSV that starts with a byte order mark (Excel's *CSV UTF-8*, comma-separated)
  imports its rows rather than being refused as unreadable, and the add form answers a name of only spaces with its own
  "Name and kcal are required" message instead of a request to the server.
- A production run no longer offers an account what its server would refuse.
  An account that may only read sees a run's status and the same notice as the
  rest of the module, without Edit, Start run, Complete run or Duplicate. An
  account that may write production but not stock is still offered Edit and
  Duplicate on a draft, but no Start run, Complete run, Finish run, portion
  form, Undo run or Cancel of a run in progress, and *New production* opens
  planning only, without the *Save as made* choice: each of those posts stock.
- The return sheet keeps to what is still left of a line. Its maximum is what
  earlier returns and corrections have not already taken back, not the full
  quantity done, so a quantity above it is named under the field and the sheet
  cannot be submitted. A line already returned in full is left out of the
  sheet, and a document with nothing left to return says so instead of
  listing lines. A leading zero no longer sticks in the quantity field of
  the return and correction sheets, packing, phone receiving, document
  lines, quick add and shopping-list add: a digit typed after a 0 replaces
  it.
- The work board no longer counts what was undone. A dispatch that has been
  undone is not counted in *Orders shipped on the order day* (undoing the
  only dispatch of the week now reads "No orders shipped yet this week"
  rather than "1 of 1 this week"), and an undone receipt is left out of
  *From dock to stock*.
- A dispatch completed from the picking summary keeps its shipment when the
  completion fails. The carrier and tracking number typed or scanned there are
  no longer lost: the document opens on the Packing step with them in its
  Shipping fields, so *Complete dispatch* there does not ship without
  tracking.
- Rejecting a document in the approval queue is written in the document's own
  journal, with who sent it back and why, as approving it already was; the
  history of a rejected document no longer ends at "Waiting for approval" while
  it is a draft again. Changing a draft's date into a closed month is refused at
  the edit, as creating a document there is.
- A read-only account no longer meets write controls that do nothing on a
  product's sheet: the photo tile, the link into the location's settings and
  the nutrition buttons are gone, and a location's page offers no **Set up
  location** to an account that cannot change it.
- The cancel dialog of a document asks its question once, the write-off of a
  scrap draft names the write-off instead of "Post this document?", and the
  phone's correction dialog names the document it corrects and wraps a long
  product name.
- A correction of a receipt that held part of a line back in quarantine
  offers and accepts only what the shelf can give: the quantity the line's own
  stock record holds, not the whole quantity received. A correction that cannot
  be applied is refused before it takes a number, so it stays a draft that can
  be deleted instead of becoming a numbered correction its author cannot
  remove, and the refusal names the product in the screen's quantities rather
  than a record id. A surplus correction is still weighed against everything
  the line received, the held part included.
- Saving a BOM's *Process steps* keeps a step that was typed in the add row but
  never added with *Add step*: it is stored as the last step, with its
  minutes, instead of vanishing under a success message. Closing the editor
  with the X while the add row still holds text asks first, and offers to keep
  editing.
- The equipment screens say what they mean. A bulk status change to the status
  an asset already has succeeds instead of reporting a failure, and the
  refusals name statuses as the screens do, in the language of the request,
  not as the stored value. The Columns menu reads *Held by*, the "only this
  page is selected" offer appears only once the whole page is ticked, and a
  viewer on an empty Templates page is no longer offered buttons that would
  be refused. Add Asset in batch mode no longer offers a serial number that
  would be dropped, bulk Assign says its checkouts have no return date, the
  attestation progress says it counts people, the overview names the retired
  assets beside the total, and the public attestation page prints its
  deadline in the organization's date style.

### Removed

- **Breaking:** `POST /api/v1/recipes/ingredient-defaults/seed`. It
  deduplicated and seeded the ingredient defaults of every organization on the
  installation, and any member of one organization could call it. A script
  that called it needs to do nothing: the recipes module does the same work
  once at start-up.

- **Breaking:** six API routes no screen or client of the app called, each
  superseded by one that stays. A script that used one switches to its
  replacement:
  - `GET /api/v1/items/expiring` — use `GET /api/v1/items?expiring_days=N`.
  - `GET /api/v1/maker/bom/parents` — use `GET /api/v1/maker/bom/summary` or
    `GET /api/v1/maker/bom/template-ids`.
  - `GET /api/v1/purchase-orders/{po_id}/approval` — list the order's request
    with `GET /api/v1/approvals/requests?target_type=purchase_order` and take
    the one whose `target_id` is the order.
  - `GET /api/v1/purchase-orders/{po_id}/html` — use
    `GET /api/v1/purchase-orders/{po_id}/pdf`.
  - `GET /api/v1/equipment/protocol/placeholders` — use
    `GET /api/v1/equipment/templates/placeholders`, which answers the same list.
  - `POST /api/v1/roles/users/{user_id}/{role_id}` — use
    `PATCH /api/v1/organizations/my/members/{user_id}/role` with a `role_id`.
    That route also refuses a member changing their own role, which the removed
    one did not.

## v0.12.0 - 2026-11-09

The first release after the public 0.11.0, and the first under a fixed rhythm:
a minor release every two weeks, on a Monday. It makes what 0.11.0 shipped
safer to run and easier to build on, rather than adding a new area.

**For people using it**, the shopping lists and the production module are
the ones that changed most. A shopping list now tops a line up when a recipe,
a meal plan or a production run needs more of it, instead of treating the line
as covered whatever its quantity, and it warns when another open list asks for
the same goods. Stock takes, returns, receiving and issuing, approvals and the
equipment register lost the rough edges a pass over every screen found, on a
phone included: nothing records a count of zero for an empty box any more, a
return can be duplicated, a saved-twice receipt leaves one draft, and a
picture replaced on a product shows at once. Recently visited fills again,
and every refusal, date and number reads in the reader's language and decimal
mark.

**For instance administrators**, an account can be created and erased from
the command line (`manage.py user create-admin --lang`, `manage.py user
erase`), the API key prefix and the default scopes of a new key give away and
grant less, the notification socket no longer writes its token into access
logs, an invitation answers every refusal with one sentence, and a few
operations steps (the update and restore commands, the off-host backup copy,
the PgBouncer connection count) are corrected. The list of what to do on the
way from 0.11.0 is below.

**For module authors**, the module rules are stricter where a mistake used to
pass in silence — a table declared on Core's base, a manifest version that
cannot be compared, a name taken by another module's pick-order strategy — and
the module SDK gains the helpers the guides asked authors to write
themselves: paging by cursor, attachment types, a quantity step, recently
visited records, a status badge permission and more.

### Upgrading from 0.11.0

Update as DEPLOYMENT.md's *Updating* says; its migration step also renames
locations that share a name under one parent (see *Fixed*). Fourteen changes break a client, a script or a module, and each says
what the affected party must do:

**The REST API and its clients**

- **Authentication errors.** A request with no credential at all to an
  authenticated route answers with the coded error object, `{"detail":
  {"code": "NOT_AUTHENTICATED", "message": …, "lang": …}}`, in the reader's
  language, not the bare English `{"detail": "Not authenticated"}`. A client
  that reads an error body in the documented order (the object, then the list,
  then the string) needs no change; one that compared the string reads `code`
  instead. The status and the `WWW-Authenticate: Bearer` header are unchanged.
- **Invitation refusals.** The refusal code `ORGANIZATION_INVITE_WRONG_EMAIL`
  is no longer sent: an invitation that is used with another address, or is
  expired, used, withdrawn or unknown, answers `ORGANIZATION_INVITE_INVALID`
  with one sentence that says what to try. A client that branched on the old
  code treats the two alike.
- **Invitation codes need an address.** `POST /organizations/my/invitation-code`
  requires `email`, the address the invitation is for, and answers 422 without
  it. A script that issued bearer codes names the invitee instead. Codes
  already issued without an address keep working until they expire.
- **Product search hits.** The document product search returns `added_date`
  (the day the record was added, a date and not a timestamp) instead of
  `created_at` on a stock hit; a client that read `created_at` reads
  `added_date`. A hit that totals several interchangeable records says
  `merged: true`.
- **Approval notes.** The approve, reject and request-approval routes of
  documents and purchase orders read the note from the JSON body as
  `{"notes": "..."}` and no longer read a `notes` query parameter. A client
  that still sends one moves it to the body, or the note is not recorded.
- **Notification socket.** `/api/v1/ws/notifications` takes the access token
  as a subprotocol, not as a `token` query parameter: the client offers
  `bearer` and then the token (`Sec-WebSocket-Protocol: bearer, <token>`) and
  the socket answers with `bearer`. A client that still sends the token in
  the address is refused with close code 4001.
- **Recipe cost lines.** A production recipe's fixed cost line takes one of
  `LABOR`, `PACKAGING`, `OVERHEAD` or `OTHER`; `POST
  /maker/recipes/{id}/cost-lines` and its `PATCH` answer 422 for any other
  `kind`. A client that sent another kind sends `OTHER` and puts what it is in
  the label.
- **Recipe picking quantities.** The recipe picking answers send
  `quantity_consumed`, `item_remaining_quantity`,
  `ingredient_remaining_quantity` (a scan) and `restored_quantity` (an undo)
  as strings, as every other stock quantity in the API does. A client that
  read them as numbers parses them as decimals. The
  `recipe.picking_completed` event keeps numbers, as every event payload does.
- **Shopping suggestions route removed.** `GET /api/v1/stats/shopping-suggestions`
  answered with placeholder figures and no screen used it. A client reads
  `GET /api/v1/shopping-lists/suggestions`, which computes them from the stock
  and its history.

**Module authors**

- **`CoreModelBase`.** A community module can no longer declare its tables on
  `CoreModelBase` from the module SDK: `module install`, `module validate`
  and module discovery refuse it, however the base is reached. A table
  declared on it lands in Core's metadata, where Core's autogenerate proposes
  it as a core migration. Declare the tables on `ModuleModelBase` and create
  them in the module's own migrations (MODULES_GUIDE.md, "Database
  Migrations").
- **Validation rules.** The core forms a module can contribute validation
  rules to are `item_create` and `item_edit`. `storage_create` and
  `storage_edit` were accepted by the type but no location form ever ran a
  rule; a module that declares one removes it.
- **Launcher badge.** A module's `useStatusBadge` hands over `labelKey`, an
  i18n key in full form, instead of `label`; the tile translates it with
  `{ count }`, so a plural follows the number. A module that returned
  `{ count, label: t("...") }` returns `{ count, labelKey: "<module>:..." }`.
- **Manifest version.** A module manifest's `version` is three numbers and
  nothing after them (`MAJOR.MINOR.PATCH`). `0.3.0-beta` and `1.0.0.5`
  validated before and could not be compared by the upgrade check; such a
  manifest is refused and its module numbers itself as three parts.
- **Pick-order strategy names.** A pick-order strategy name belongs to the
  module that registered it first. `warehouse_api.register_pick_order_strategy`
  raises `ContractViolationError` for a name another module holds, where it
  used to replace that module's strategy, the default walk included, in
  silence. A module that reused a name registers its own.

Not marked **Breaking**, but worth a look before you update:

- A new API key no longer starts with the permission to read the
  organization's details and member list. A script that creates a key through
  `POST /api-keys` without naming a permission gets a key that answers 403 on
  `/organizations/my/members`; name `org:read` to keep the old behaviour.
- An API key's shown prefix is `inv_live_` and six characters, where it was
  eleven, on the API keys page and in the audit log. Existing keys are
  shortened on upgrade and keep working. Audit entries already written keep
  the longer prefix, which still begins with the short one, so a script
  comparing prefixes compares the start.
- The backend's memory limit defaults to `2g` instead of `1536m`, so the four
  workers it starts by default fit the size DEPLOYMENT.md gives one. An
  installation that sets `BACKEND_MEM_LIMIT` in `.env` keeps its value.
- An installation that enabled the Open Food Facts database or the off-host
  backup copy with `--profile` on its commands adds the profiles to
  `COMPOSE_PROFILES` in `.env` before its next update (see *Fixed*).
- `GET /items/archived` answers `next_cursor` and takes `cursor`; `offset`
  still answers and is deprecated.
- An item edit or a new record that sends a unit weight for a product from the
  shared catalogue is refused with `UNIT_WEIGHT_OF_SHARED_PRODUCT`; sending the
  weight the product already records is not a change.
- Equipment attachments and product files take one list of file types: the
  old binary Word format (`.doc`) is refused by both, and Equipment takes
  `.zip`.
- Webhook endpoints subscribed to `item.transferred`, `item.deactivated` or
  `item.status_changed` show them as withdrawn; nothing ever sent them.

### Added

#### For people using it

- **Shopping lists** top up a line that is already on them. A recipe added to a
  list that carries its ingredient raises the line by what that recipe needs;
  a recipe the line was made for raises it by what it now needs beyond that
  (more servings, or less of the goods left on the shelf); "Update list" on a
  meal plan raises a line when the plan needs more; and a production run's
  shortage raises the listed line when the run needs more. A line already
  ticked off keeps its quantity and the rest becomes a new line; a line is
  never lowered. A line of the same product in another unit counts as its
  amount in the unit asked for, so 500 g of plums already listed leaves 3.5 kg
  of a 4 kg shortage to buy (it used to count as 500 kg), and a line in a unit
  that does not convert covers nothing. Recipes added together subtract the
  stock on the shelf from what they need between them, not each against the
  whole shelf, and a "From recipes" sheet that adds nothing because the list
  already asks for all of it says so.
- When a recipe's "Add missing", a meal plan's "Generate Shopping List" or a
  list's "From recipes" writes goods that another open shopping list still
  asks for, the answer names them and the list that holds them
  (`on_other_lists`), and the screen says so in a toast and, on the meal plan,
  in the panel that stays. The lists are still written as asked.
- A production run's shortfall put on the shopping list rounds up to the
  ingredient's own unit step, as the recipes module rounds a requirement, so
  an ingredient counted in pieces that is 1.5 short asks for 2 pieces, and the button that puts it there states the same quantity.
- Asking for an approval warns about a later stage nobody could decide, not
  only the first. The dialogs behind Confirm and Send for approval on a
  document and on a purchase order name the first stage with no possible
  decider and what ends the wait (grant the named people access to approvals,
  give someone the permission, or withdraw the request). A purchase order
  whose request was withdrawn and that asks again gets the same warning from
  its approval card, and the notice for a request stuck at such a stage no
  longer promises that withdrawing it returns the order to Confirmed. A stage
  that names the person who raised the request beside people who cannot
  decide it is a dead end, and is reported as one in the queue, the dialog and the notice.
- The approval queues show a document's net amount and say that it is net, the
  side the approval threshold is set on, and the notice to an approver names
  the document, who asked and the net amount, in the app and by e-mail. A
  write-off is weighed against the threshold at what the goods cost.
- The name field of a form that creates a product offers the products already
  in the catalogue whose name contains what is typed; picking one writes its
  exact name, which is the match the save attaches the record to. Typing
  "Wax" no longer leaves a second product beside "Soy wax".
- Under an empty product code field, the product form says what **Generate
  code** gives: an in-house code starting with 20, from the range GS1 keeps
  for a company's own goods, valid only inside the organization. An empty
  Products list says that products which exist only as a definition, such as
  ones made inside a recipe or a BOM, appear there once they have stock.
- The stock-on-a-date report can be narrowed to a product and to the place you
  had narrowed to; the spreadsheet, the printout and the `search` parameter of
  `GET /stock-as-of` follow the same text, and a printout of one place names
  the place beside its dates ("Main Warehouse › Fridge › Fridge A").
- Smart alerts state how far off an expiry date is ("Expires on 12.11.2026, in
  3 days"), colour a date within the week amber, and name the place and the
  batch (`location_name`, `lot_name` in `GET /stats/smart-alerts`).
- The expiry date picker starts with a week, two weeks and a month. Receive
  goods and Issue goods can add a supplier or customer that does not exist yet
  without leaving the form.
- Settings has a "People" entry in its sidebar and phone menu that leads to
  the members and invitations; the webhook dialog lists every event in the
  interface language and sets apart the events of modules the organization has
  not enabled.
- A confirmed document keeps your own company's name, tax number and address
  and the names of the locations it refers to, as it already kept the
  partner, so a reprint after the company moved or a shelf was renamed shows
  what the original showed; the record a closed stock take leaves keeps them
  too. A document confirmed before this prints the current details.
- Creating an account (the first one, by invitation or from an approved
  request) signs it in and continues to the app; if the sign-in is refused,
  the form opens with the address filled in. A password-reset link that is
  spent or expired is refused when the page opens (`POST
  /auth/password-reset/check`), with a link to request a new one.
- A purchase order line picked from the catalogue starts from the price the
  product last cost, and a custom purchase order template prints the values
  its editor lists (`{{po_number}}`, `{{vendor_name}}`, `{{barcode_img}}` and
  the rest).
- A recipe's page and printout show a dash for a nutrient no ingredient
  measured, where the sum would have been 0 (a rice dish where only the chicken
  had values read "Carbs 0.0g"), and "Calories unknown" instead of "0 kcal".
  The meal plan dialog that has no plan yet says the recipe is added to the
  first meal of the new plan at once.
- A low-stock alert for a product with no preferred supplier proposes the
  supplier of its cheapest current price-list entry, and a draft purchase
  order made from it goes to that supplier.
- A module's settings schema may mark an option `requires_modules`: the option
  shows only while those modules are enabled. The recipes option "Register
  production as internal issue documents" uses it.
- `POST /warehouse/documents`, which writes a draft, takes an `Idempotency-Key`
  header as `POST /warehouse/documents/post` does: the same key sent again is
  answered with the draft the first request wrote. A request without the
  header writes a draft each time, as before.

#### For instance administrators

- `manage.py user create-admin` takes `--lang` (`en`, `pl`, `de`, `fr`, `es`
  or `pt`) to set the language the account opens in (an unknown code is refused, and
  without it a new account takes the instance default and an existing one keeps
  its own); DEPLOYMENT.md
  and QUICK_DEPLOY.md say how to use the command to get back into an installation
  without outgoing mail.
- `manage.py user erase <user id>` erases one person's account on a GDPR
  erasure request: it shows whose account it is and asks first (`--yes` skips
  the question), replaces the address, name and password, closes the account
  and revokes its sessions in one transaction, and reports "Nothing was
  erased" with exit code 1 when a step fails, Redis included. It also clears
  the reason an operator wrote when blocking the account and finds the
  person's registration request however the address was capitalised. It
  replaces the Python script GDPR_MANUAL_PROCEDURE.md asked operators to
  paste; the procedure says now that the user id the journal keeps is
  pseudonymised personal data, and that records an organization keeps about
  people (equipment handed to them, their answers to an equipment check, a
  contact or employee card) are not rewritten by the deletion.
- `PGBOUNCER_MAX_CLIENT_CONN` in `.env` sets how many connections PgBouncer
  accepts from the backend (300 when unset, as before). Six workers open up to
  300, so DEPLOYMENT.md's 16 GB sizing row sets it to 400.
- The 409 refusals of focus mode, of a profile switch and of onboarding with a
  module chosen carry `lang` and the data their message is built from
  (`module`, `unknown_modules`, `not_allowed_modules`, `modules` or
  `missing_dependency`) next to `code` and `message`, so a client can name the
  refused modules without reading them out of the sentence.
- When a handler of an event that belongs to no organization is given up on,
  the instance's superusers are told, in their own language and once a day per
  handler, as an organization's admins are for its own events.
- A multi-node deployment no longer collects a dead member in the event and
  task stream groups for every restart: a reaper removes consumers that have
  held nothing for an hour, a clean shutdown removes the event bus's own at
  once, and a message a crashed node had read but not finished is redelivered
  when the replacement starts (`docs/SCALING.md`).

#### For module authors

- The module SDK gains `hit_constraint` (did this integrity error trip one of
  the named constraints), `rows_to_csv` (rows to CSV text with every data
  cell defused against spreadsheet formulas) and `utc_now` (the timezone-aware current moment); `cover_leaf` and
  `cover_leaf_of` name and read a cover file; the frontend `@/module-sdk`
  gains `useIsSignedInAs` (is the signed-in user the person a record names by e-mail address), `useKeysetPaging` (a list the server pages by
  cursor), `useRecordVisit` (a record page in **Recently visited**),
  `ATTACHMENT_FILE_ACCEPT`, `QUANTITY_STEP`, and the `Item`, `StorageType` and
  `ScannedTemplate` types, `useAppMutation`, `useModules`,
  `PageHeaderContext` and the overview's `AttentionCard` that its own
  contract and the guides ask a module to use.
- A module names the read its launcher badge asks for with
  `statusBadgePermission` on its `FrontendModule`; the launcher calls
  `useStatusBadge` only for a role holding that key, and the tile shows no
  status for any other role instead of "Status could not be read". A module
  that leaves it out is asked of every role, as before; an action-items hook
  keeps asking for itself and should do so only when `useHasPermission` grants
  the read (FRONTEND_MODULE_GUIDE.md shows how).
- A module that prints its own documents through the core print identity can
  freeze the issuer block with `issuer_snapshot` and
  `IssuerContext.from_snapshot`. A module's own request that saves nothing
  passes `{ readOnly: true }` as the request config to the `api` client from
  `@/module-sdk`, and gets the plain "session has ended" sentence (see
  *Fixed*).
- A module's `on_enable` (and `define_module(seed=...)`) runs whenever the
  module is enabled for an organization, onboarding and the demo seed
  included; a module that seeds there no longer leaves every onboarded
  organization without it. A module no longer has to call `super()` from
  `on_startup` or `on_install`: the framework registers its services and
  contributions, wires its interceptors and runs its migrations itself
  before the hook. An item interceptor overrides only the hooks it needs.
- `module validate` reads a package the way `module new-community` writes it
  and checks its backend laid out the way `module install` lands it, and
  `--allow-core` skips the safety scan only for the modules this repository
  ships. `module install`, `module upgrade` and `module validate` refuse what
  discovery refuses at the next start (a manifest `name` other than the
  directory, a `module_type` above `community` from outside the repository, a
  platform floor above the running version) instead of printing success, and
  accept a `requires` entry naming an always-on feature.
- A module's document filter can count only the lines that carry a batch
  (`DocumentFilterDTO(lots_only=True)`); the lot certificates example uses it.
- In development, the browser console names a module's `navOverrides` entry
  whose `targetPath` is no navigation item, an `i18nOverrides` key that no
  catalog has, and a navigation item with a relative path; registering a
  contribution to `scan_providers` or `dashboard_widgets`, which no backend
  code ever read, logs the warning of an unknown point. The safety scan reads a banned import as the module and the modules inside
  it, so `socketserver` is no longer refused as `socket`, and accepts `from
  app.core import module_sdk`.

### Changed

- A refused invitation answers with one sentence that says what to try — use
  the address the invitation was sent to, or ask for a new one — and the same
  sentence for a wrong address, an expired, a used, a withdrawn and an unknown
  code, so it tells nobody which of them it was. The public link check
  (`GET /public/invitation/{code}`) keeps answering a dead code with a 404 and
  asks for a new link.
- `GET /items/archived` pages by the last record seen, as the stock movement
  ledger and the audit log do: `next_cursor`, `cursor`, a count on the first
  page, and an order by id for records archived at the same instant, so a page
  deep in a long archive costs what the first one does and turning a page
  shows no record twice. The archive screens of the product list and of
  Equipment page this way.
- Equipment attachments and the files attached to a product accept one list
  of file types, and the pickers no longer offer `.doc`, which the server
  refused only after the upload. The size limits stay: 20 MB for an equipment
  attachment, 10 MB for a product's.
- The reason "Consumed" reads the same everywhere it is shown, in every
  language; the Polish approvals and document settings call the module by its
  name, "Zatwierdzenia". The module store in Settings is headed "Modules",
  the Statistics settings link carries the module's own name, and removing a
  member asks "Remove <name>?" and says that person loses access at once.
- A refusal about a closed period names the month as the period screen does
  ("September 2026"). Amounts in a unit that is a word take its plural ("6
  bottles"). The short-pick dialog says "Cancel" and the picking sheet's main
  button "Complete picking", as their receiving counterparts do, and the
  equipment note beside the item actions calls the action "Return".
- Saving a module's settings, signing in and every refusal use the reader's
  language: the confirmation after saving a module's settings and after
  signing in, a "not found" answer on every endpoint (a module's
  `NotFoundException` raised without a language speaks the request's
  language), a request refused for the general rate limit (`lang` beside
  `message`), a bulk edit of an asset's status, a warehouse document import
  row (which carries its code), and a validation error that names a decimal
  bound, written in the reader's decimal mark.
- The audit log writes the quantities and amounts of a production order, its
  completion, a recipe and its lines, and of an item's creation, use,
  disposal, deletion and restoration, and the low-stock threshold, as the
  exact digits the record holds; a production order of 1,234.567 read 1,234.57
  in the log. The product history does the same for a use, a disposal, a scan
  that adds to a record, a deletion and an opened package. Entries written
  before keep their numbers, and the history screen reads both.
- The journal names the custom role an invitation offers and a print layout by
  the name the settings screen gives it, and marks the settings a workspace
  mode writes as "Workspace mode default". A day's activity and History state
  the stock change of a correction with its sign ("by +1" for taking one piece
  off an issue).
- A webhook endpoint switched back on in its edit form starts its failure
  count again, as Reactivate does; a retried delivery sends the bytes of the
  first attempt, so its signature is the same. `GET /stats/consumption` fills
  `consumption_by_category`, which was always empty.
- The statistics screens count stock rows as records, name products without a
  category in the reader's language, list the fullest places first and leave
  out the system's consumed, loss and production places.

### Fixed

#### Access and security

- A custom role holding only a module's read opens that module's screens
  whole. Equipment's asset list, filters, archive and card read the locations,
  categories and archived records they show, its label download answers the
  register's read, and Warehouse's codes page reads the locations and
  categories it lists; each of those calls answered 403 before and the screen
  showed an empty list. The read still buys no core write, and no reach past
  the module's own records.
- The equipment register's routes that name one asset (valuation,
  attachments, approval state, assignment and maintenance history, timeline,
  check-out, service entry, status change, retirement, archiving) answer only
  for the records the register lists. A role holding only `equipment:read` used
  to read the name, serial number and purchase price of any product whose id
  it knew, and a retirement sent through the register changed an ordinary
  product; such a record now answers 404. A print job of pool labels sent with
  the register's read takes only labels assigned to its records.
- The home screen no longer asks for the status of a module the signed-in role
  cannot read, so such a tile shows no status and such a To do row does not
  appear, instead of "Status could not be read".
- The error details a broken screen offers to copy into a bug report no longer
  carry the token of the link that opened the page (password reset,
  invitation, registration, equipment attestation): it reads `redacted`.
- A module's stored file path with a `..` segment is refused (`StorageError`)
  instead of resolving outside its folder on the local disk, and a missing file
  is a `StoredFileNotFoundError`. An equipment attachment on a bucket (S3)
  backend opens through the app's own `/uploads/…` address, which checks who
  is asking, instead of the bucket's bare address.
- A search or any text a request sends that holds a null character is refused
  with a 400 (`TEXT_HAS_A_NULL_CHARACTER`); a request whose `X-Request-ID` or
  `Accept-Language` carries a byte outside UTF-8 is no longer answered with a
  500, and a client's `X-Request-ID` is kept only as 8 to 64 letters, digits
  and hyphens. A 500 answer carries `X-Request-ID` like every other.
- Closing or reopening an inventory period refuses a month outside 1–12 or a
  year outside 2000–2100; pasted import text past 50 MB is refused with a 422.
- Uploading a picture that only starts like one is refused as unreadable; a
  logo uploaded as WebP prints through `{{ issuer.logo }}`; an organization
  template keeps an `alt`, `title` or `class` beginning with "Data:".
- A Google (Gemini) connection keeps the same time limits as every other
  provider (`LLM_REQUEST_TIMEOUT_SECONDS` for a call, 30 seconds for the model
  list on the connection test) and a Gemini outage answers 503 with the sentence that names it. A
  label photograph sent to `POST /vision/extract` is fitted into 1200 × 1200
  px before a model sees it.
- A module rejected at startup no longer leaves its permissions in the roles
  editor, the API key dialog and the built-in role defaults. A signing key
  listed without an id is skipped with a warning that says so, and a failed
  signature names a different key under the same id as one of the two
  possibilities.

#### Time and numbers

- Which day it is comes from the organization's clock in the places that still
  read the server's: the shopping-list suggestions, the reserve stock
  replenishment offers, the date a production run with no production date is
  filed under (and the closed-period check on it), and the year in the number
  of a document with no date of its own. An organization a day ahead of or
  behind the server saw each of these a day off, and a document was numbered
  into the old year just after local midnight on 1 January.
- Spreadsheet exports store a figure as the screen shows it (95.35, not
  95.34999999999999). A recipe picking leaves what is written to the record
  on the shelf, not a float subtraction (0.1 kg from 0.3 kg left
  0.19999999999999998). "Max batches from stock" shows ten as 10, not 1E+1.
- The shopping list's refusals of a quantity and the "at least" message write
  their numbers in the reader's decimal mark ("0,001" in Polish), and the two
  ways of adding an item state the same rounded value for the same request.
- The consumption report's two top-ten lists order equal products by name, so
  a tie at the tenth place no longer changes from one reading to the next. An
  organization with more than 500 records gets its forgotten-product alerts
  from its stalest records.

#### Stock, products and locations

- On a stock take, Save on an empty or unreadable count box no longer records
  a count of zero; a note typed on, changed on or cleared from a counted line
  makes the line read as unsaved and enables Save; and Complete stock take
  waits until the saved count is back, so it no longer refuses with "one
  product is still uncounted".
- Two locations can no longer be saved with one name at the same level by two
  people, or a retried request, at the same moment, and the database holds the
  rule too. On upgrade, places that already shared a name under one parent
  keep both: the newer one is renamed with a number, such as "Cellar (2)".
  Saving two partners with the same name or code at once is refused with the
  usual "already exists", and refusing a partner that exists names its type
  in the reader's words ("Supplier", "Dostawca").
- Archiving a location whose records have to go somewhere offers every other
  location as the target, sublocations included. Locations: an address that is
  not a location identifier shows the same "not found" page as an unknown one,
  an empty location no longer offers a button to an empty Products tab, the
  archived locations are reachable from a phone, and the location wizard no
  longer replaces a name already typed when a chip is pressed or suggests a
  name taken by a module's location or an archived one.
- Replacing the photo of a product, an asset or a recipe shows the new picture
  at once (every cover was kept under one address); a photo picked in the
  product edit sheet is saved with Save changes and dropped by Close; a
  product's thumbnail returns to its picture when the server refuses a new
  one. Stored photos load on an instance that serves the app straight from the
  frontend container without Caddy, which answered every `.jpg` and `.png`
  under `/uploads/…` with its own 404.
- The product list keeps its order when you come back (the sort is part of the
  address), ticking two filter chips quickly keeps both, "expiring soon" and
  "expired" no longer stay on together over an empty list, and a product's
  place is blank, not "Unknown", while its name is on its way.
- A product used up to zero reads "Consumed" and no longer offers "Add 1
  unit", which was refused after the click. A product name longer than 100
  characters can be searched, a failed search is reported as failed with a
  retry, and the product search no longer empties itself on a scroll event.
  A product form whose category list could not be loaded says so and offers a
  retry; Add Category opens empty on the product and equipment screens alike.
- Product distribution by location no longer lists archived locations or a
  container with no records of its own as an empty shelf. Warehouse
  occupancy no longer suggests a cheese in its search box on every profile, and
  the statistics page no longer calls a warehouse's stock supplies. A stock take
  report shows a surplus in blue, like its Overstock tile.
- A row of the inventory overview about a date opens the product with its
  expiry date in view. On an organization seeded before the option words
  existed, the "Lactose free" field of the Dairy and Cheese categories offers
  its options in the interface language.
- The product label dialog no longer shows "Lot and expiry date" ticked while
  disabled, and printing a list of labels gives a sheet of rows, three across,
  in the preview and the download. The scanner's Back button leads to the
  launcher when the scanner was the first screen of the tab.

#### Documents, warehouse and approvals

- A return can be duplicated: Duplicate used to be refused with "Invalid
  input" and now writes another draft return of the same document, counted
  against what is left to return on it and refused in the same words as a new
  return when too little is left. A return saved from its edit form keeps
  counting against its original, editing a draft return offers the kind of
  partner the goods go back to (suppliers for a receipt, customers for a
  delivery), duplicating a correction through the API answers
  `DOCUMENT_CORRECTION_NOT_DUPLICABLE`, and a copy of a receipt whose line
  named only a stock record keeps that record.
- Saving a receipt as a draft again after the answer was lost on the way back
  (a phone changing networks) no longer leaves a second draft behind.
- A completed dispatch keeps its **Packing** card, read-only, with each package's
  slip and label and the file of all slips; a picking session over one
  delivery, however it was opened, ends with **Pack**, the shipping fields and
  **Complete and book** (opened from the documents list, **Close** used to
  complete nothing and offered neither); the carrier
  typed on the picking summary is still there when packing opens.
- A document that waited for an approval when the approvals module was
  switched off is worked as a confirmed one, and starting that work takes it
  out of the queue for good (its read carries `hold_stood_down`). A purchase
  order's approval panel follows the approvals settings without a reload, and
  a note written when approving or rejecting a purchase order is recorded; it
  used to be lost between the screen and the server. Completing a purchase
  order sends one notice per person.
- The Receive goods, Issue goods and Move goods forms mark a missing value
  where it is and say why once, and an error under one field no longer pushes
  its neighbours out of line. A posted receipt says which of its lines have no
  price, and a document form says so under a line the price books and past
  purchases have no price for. An issue dated today can be planned from its
  page.
- On a phone, the picking and receiving lists show the whole product name and
  the whole batch and location code, a purchase order's main action sits on
  its bar, the new partner sheet keeps Save in view, the statistics tabs fit
  the screen and the product suggestions open above the keyboard.
- A fault while reading the documents awaiting your approval, or a supplier's
  pricelist for a price suggestion, is answered as a server error and logged;
  the list used to come back empty. Exporting the document register to CSV no
  longer loads every line into memory (20 000 documents of ten lines takes half
  a second instead of seventeen and 40 MB instead of 1.2 GB), and a period that
  ends before it starts answers 400.
- Smaller things on the warehouse floor: a camera without a torch no longer
  offers the light switch; the lot on the receiving expiry sheet and a
  product's own code can be read with the camera; the document scan
  confirmation and the unit question name the unit in the interface language;
  a correction draft says in words which lines are added to or removed from
  stock; "Recently visited" on the launcher and the command palette fill again
  (nothing recorded a visit).
- A purchase order mailed to the supplier, and the mail of the approvals and
  equipment modules, leave through the mail server the organization set in
  Settings → Email, as invitations and password resets already did.
- Saving a supplier price or a reorder rule without a product marks the field,
  a maximum below the minimum is refused on the Maximum field, and on a phone
  the reorder rules are cards. The purchase-order approval warning names the
  threshold when it is the requirement left, and the message for a missing
  approval workflow tells a storekeeper to ask the administrator.

#### Production, recipes and meal plans

- Importing ingredient data no longer loses the whole file when one row is
  refused: the row is counted as an error and the rest are saved (a name too
  long for its column used to answer 500 and roll back the good rows too), and a
  blank name is refused by the form and counted as an error by the import
  rather than saved as a nameless entry. A file with no usable
  row (an empty sheet, a photo, a bank statement) or that holds no list of
  rows answers with what the import expects in every maintained language,
  instead of a green "0 added" or the parser's own words.
- The maker's "Block" shortage strategy holds against an API request that
  sends `confirm_shortage`, duplicating a run the stock cannot cover is refused
  under it (422 `shortage_blocked`), and `GET /maker/settings` documents
  `WARN` as the default. The composition tree on a variant's page shows that
  variant's ingredients; `GET /maker/bom/{template_id}` and `GET
  /maker/bom/tree/{template_id}` answer one recipe (`recipe_id=`, else the
  default one).
- A product whose nutrition came from Open Food Facts counts its calories in
  recipe estimates and the meal plan's daily totals. A recipe ingredient typed
  by hand whose name has accented letters ("Ryż") finds the product on the shelf
  ("Ryż 1 kg"). The stock changes a production run and its reversal write carry
  a reason in the interface language followed by the run's number, the cost
  line names the unit the run is counted in, and a recipe's page prints its
  name once.
- The cooking screen states the amount a pick took in the reader's number
  format, closing "Take from stock" no longer marks the recipe as cooked, the
  new production dialog writes the unit as the rest of the app does, and the
  onboarding card for working with a single module names Production.
- The empty state of the ingredient dictionary no longer promises a fallback to
  English: it says suggestions come from matching entries in any language, the
  current one first, which readers in French, German, Spanish and Portuguese,
  whose dictionaries start empty, see on every installation. The sentence about which units are offered takes the full width
  of the ingredient form.

#### Equipment

- Handing an asset back, from "My assets" or its own page, opens a dialog worded
  for the person returning it, and the holder's history prints days and
  conditions in the interface language. The Check Out Asset dialog names an
  address nobody in the organization uses before it saves it, also when the
  address is pasted and submitted at once.
- The overview counts a new asset as soon as it is saved, and three numbers
  agree with the lists behind them: a category row leaves out retired assets
  nobody holds and the list it opens does too (a "Retired hidden" chip brings
  them back; `GET /equipment/assets` takes `hide_retired`), and the attention
  card reads every late return, not the first twenty.
- Smaller things a regression pass found: adding an asset opens it and
  retiring one keeps you on it; the public attestation page says which
  organization asks and by what day and shows its ticks in the success colour;
  an import that lost rows says so and names the duplicates it skipped;
  deleting a category says what goes with it; a dispute note names the asset by
  its serial number; the sheet that issues an asset keeps its buttons in view
  on a phone; the German screen is "Meine Geräte" and the Polish module speaks
  of issuing (*wydanie*) throughout; the date picker prints a day the way the
  rest of the application does.
- Dialogs say what failed: creating a location, saving a stock alert, a bulk
  edit, changing a batch's status and freeing a label name the write that could
  not be done instead of "Unknown error", bulk edit's Apply waits until a field
  is ticked, and an empty service entry marks every missing answer in the app's
  language.
- Module settings with a bounded number (such as the equipment warning window)
  answer a value out of range in the app's own language rather than in the
  browser's.

#### Smaller corrections

- When the session has ended, a request that was only asking (a label preview,
  a pasted-lines or sheet read, a price calculation, a match or coverage check,
  a connection, webhook or e-mail test, a generated barcode) gets the plain
  sentence that the session has ended, not "this was not saved, sign in again
  and start over", which was false for work that had saved nothing. On the
  equipment form, a refused photo removal after the asset was saved is
  reported as that, not as a failed upload.
- The answers of `PATCH /documents/{id}/confirm`, `.../complete` and `POST
  /documents/{id}/post` carry `confirmed_by_name` and `completed_by_name`,
  which were `null` until the document was read again. Start and Board name a
  draft task the way the document's own page does ("Delivery – draft 6CCF"),
  not by its internal identifier, and the Polish refusal to finish a document
  with an open picking or receiving session agrees with the number of
  sessions.
- The symbol list in the document and equipment template editors reads as
  something a template author can use: record-valued symbols (`totals_by_unit`,
  `packages`, `pick_lines`) show their fields instead of Python dictionaries,
  the examples are in the editor's language, and `GET
  /warehouse/templates/placeholders` answers in the request language. The
  built-in layouts in the template preview carry their translated names
  ("Standard layout", "Pick list").
- A module that is switched on says on its store card when a module it works
  better with is switched off, and the roles screen names a module with no
  translation of its own by the name in its manifest. Deactivate on a module's
  card reads as a button, and choices drawn by colour alone (the Production
  settings groups, the tracked fields of a location) report which option is
  selected to assistive technology.
- The "Show inventory value" setting says that it also governs the product
  screens, exports and printouts, and a profile that hides stock value no
  longer shows it for a moment. Add product shows pieces on its unit button
  when no unit was chosen, which is what the save has always filed such a
  product as. The action sheet opened from a location's products or a scan
  explains why an asset's actions are worded differently, as the product page
  does, and is silent about it for an account that may not act on the record.
- The expiry forecast tiles sit two across on a phone and three across below
  1280 px, so no label breaks inside a word in any of the six languages. In
  Polish the Batches status tabs read as plurals; the Desktop Computer,
  Network Device and Peripheral equipment presets have icons; the AI
  connections page no longer shows its title twice.
- A row of a warehouse document import that fails in the database shows the
  generic sentence instead of the statement that failed.

#### Running it

- DEPLOYMENT.md's update and restore steps reach the Open Food Facts database
  and the off-host copy: the guide enables their profiles with
  `COMPOSE_PROFILES` in `.env`, which every compose command reads, where a
  `--profile` typed on one command left the services out of the next update's
  recreate and out of `down`.
- The off-host backup copy sends each backup once; it followed the `-latest`
  links in `backups/last/` and uploaded the newest dump and archive twice under
  those names, and its next pass removes those copies from the remote.
- `DEFAULT_LANGUAGE` reaches the backend container on the development and the
  production stack and is in `.env.production.example`; an account created
  without a language started in English whatever `.env` said.
- `manage.py db stamp-module` works on a database a newer version has already
  migrated, the way `db doctor` tells you to use it. The index on `audit_log
  (organization_id)` is dropped by a migration; the two composite indexes on
  the journal serve every read it did.
- A scheduled task registered as persistent on an installation without Redis
  logs that it runs in the process and that a missed run is not made up. The
  production Content-Security-Policy admits the web worker that shrinks a
  photo before it is sent. The first open of the application shows the
  product name and a loading sign instead of a white page, and tapping a
  screen for the first time shows a loading sign at once.
- `make new-module` stops at a step that fails instead of carrying on to
  "SUCCESS" and a second run picks up at that step; `module new-community
  --language` lists every language it accepts; a generated community module
  asks for its own read and write permissions on every route. On the
  development stack, installing or upgrading a module while the app is open no
  longer leaves the page on the error screen until it is reloaded.
- A settings schema that declares the reserved `__schema_version` key in a
  nested object is refused whether or not the saved settings reach it. A module
  navigation item with a relative path is named in the development console and
  the scaffolds write the full path.
- Demo data charges the tax of the organization's country, and none where no
  country is set, instead of Polish VAT on every order and document.

### Removed

- `GET /api/v1/stats/shopping-suggestions` (see *Upgrading from 0.11.0*).
- The webhook event list no longer offers `item.transferred`,
  `item.deactivated` and `item.status_changed`: nothing sends them, so an
  endpoint subscribed to one never received a delivery. A new subscription to
  one is refused; an endpoint that already names one shows it as withdrawn,
  and the edit form lets you remove it.

## v0.11.0 - 2026-11-02

The first public release, and the one that makes the warehouse documents a
light warehouse management system that an ordinary phone can run. Deliveries
are received and orders picked with the phone's camera; several dispatches are
picked in one walk along numbered locations; picked goods are packed into
numbered packages, each with a slip and a label; and a dispatch leaves with
its carrier and tracking number recorded, linked to the carrier's tracking
page and announced by a webhook. The user guide walks the whole path in "From
pick to parcel". Left out on purpose: no carrier is contacted (no carrier
labels, rates or status updates), dispatches are not grouped into waves, and a
return is a document rather than a process.

This is an **alpha** release. The REST API as a whole is experimental in
0.11: its routes and bodies still follow the screens they serve. Three parts
of it are stable from 0.11.0, with a guard each. **Every collection is a
page**: `{"items", "total", "limit", "offset", "has_more"}`, with `limit` and
`offset` query parameters. Each list states its own default and ceiling in
the API reference: most take 50 rows by default and 200 at most, the product
list 100 and 1000. The
feeds that page by cursor (item history, webhook deliveries, the stock
movement ledger, the audit journal) answer with `next_cursor`, and the 27
routes that are not a collection of rows — a fixed vocabulary, the six expiry
buckets, the newest-N activity feed — stay plain arrays and say why beside the
route in the code. A list that grows with the organization — the products, the
stock, the movement journal — counts at most ten thousand rows and says so in
`total_capped`; the documents and purchase-order lists carry each document's
lines counted and summed, and the document's own address carries the lines.
**A business refusal** answers with its own machine-readable code, the
upper-cased key of its sentence in the message catalogue, and the translated
sentence in `message`; the codes are listed in
[`docs/api/ERRORS.md`](docs/api/ERRORS.md#refusal-codes). **API keys** have
their own header and permissions. The contract DTOs, the stable `core_api`
namespaces, the module manifest, the webhook envelope and the print protocol
are the other surfaces to build on;
[`docs/subsystems/CONTRACTS_STABILITY.md`](docs/subsystems/CONTRACTS_STABILITY.md)
lists every public surface and the promise its class makes.

### Added

#### Stock, at home, in the office or in a warehouse

- **A tree of locations of any depth**, shown as a path (`Home › Garage ›
  Shelf A`), with products allowed on any level. Moving a location that holds
  stock asks whether it was carried somewhere else or the layout is only being
  corrected, and a physical move is recorded for everything inside it.
- **Products and their records**: quantities in the product's own unit,
  batches with a state (active, quarantined, recalled…), expiry and freeze
  dates, reservations, a minimum quantity with a running-low rule, and custom
  fields — set on a location, a rack or a whole warehouse and asked of every
  product placed below it. Products import from and export to a spreadsheet; a
  sheet of more than 200 rows is imported as a job the import screen follows
  (`POST /items/import` answers `202`, the job is read at
  `GET /items/import/jobs/{id}`). The export of a large catalogue is written
  row by row, so it does not grow the server, and continues on a second sheet
  past a million rows. An opened package can have its own use-by date; its
  expiry is the earlier of that date and the batch's expiry.
- **Which stock leaves first** is set per product — FIFO, or FEFO by earliest
  expiry — and a category gives the products created under it their starting
  setting.
- **A journal of every movement**, and the stock as it stood on any past date.
- **Stock takes**: count a location from a phone or a desk, blind if the
  counter should not see what is expected, shelf by shelf with the phone's
  camera; **Close location** counts what nobody found as zero. A count that
  changed the stock writes one numbered adjustment, and a setting puts every
  location in To do once it has gone a chosen number of days uncounted.
- **Labels**: QR codes for products and locations from a label pool, an
  internal EAN-13 for a product without a manufacturer's code, product labels
  with the code as a barcode and the lot and expiry date, and shelf labels in
  Code 128, which a phone's camera reads as well as a 1D scanner. Labels
  download as images or print through the print agent (a Brother P710BT, a
  CUPS queue or any command).
- **Scanning**: the camera of an ordinary phone, on every scanning screen — no
  scanner to buy. A USB or Bluetooth scanner that types like a keyboard is
  supported on the same screens, but has not yet been tried with real
  hardware. A product scan says where each record stands; a location label
  says what is on that shelf and how much.

#### Warehouse

- **A start screen made of the day's actions** — Receive goods, Issue goods,
  Move and Count — each one screen on a desk and on a phone. The numbered
  document the office needs is written in the background, and every posting
  answers with that document, prints it and offers Undo.
- **Numbered documents in your own vocabulary**: eight neutral codes (`IN`,
  `OUT`, `INT`, `INTERNAL_IN`, `INTERNAL_OUT`, `CORRECTION`, `ADJUSTMENT`,
  `SCRAP`) named by the profile — PZ, WZ, MM, PW, RW for "PL Magazyn"; GRN,
  DN, ST for "UK Warehouse", WE, WA, UML for "DE Lager", BR, BL, BT for
  "FR Entrepôt", AE, AS, TR for "ES Almacén". A draft posts in one action; a posted receipt,
  issue, move or write-off is undone in one press where nothing has used the
  goods since. A write-off records why (damaged, expired, quality, other —
  required wherever it is posted from) and what it cost, from the cost layers
  it drew, and its printout says both (the cost is left off where the layers
  could not value the goods). A document register, closed
  periods, bulk confirm and one PDF for a selection; the register says when
  its totals include scrap and how many documents were posted without a
  price. A printout follows the organization's country — the Polish PZ form
  for Poland, the standard layout elsewhere — and the language it is asked in.
- **Receiving**: one sheet that asks where the goods come from — a
  supplier, a customer's return or an internal receipt — loads what the
  supplier's waiting purchase order still expects, takes rows pasted from a
  spreadsheet and posts with one press; on a phone, one card per item with
  large buttons. Each line names
  the shelf the putaway rules chose and why. A location can receive in two
  steps — into a receiving area, then put away as tasks in To do. More than
  an order expects is refused past its tolerance, except for someone allowed
  to receive over it, who is first asked about every surplus the delivery
  brings; a warehouse setting caps the surplus nobody may pass. A line says
  how much of what arrived is damaged or waiting for a quality decision and
  why, on the sheet and on the phone's card: that part goes to quarantine, and
  the order counts the whole delivery as received.
- **Putaway and occupancy**: putaway rules with the fill of each of their
  shelves, product limits per shelf, and one screen showing how full every
  location is, as a tree or a heat map. Putting goods away somewhere other
  than the suggestion asks whether that place is now the product's home — an
  ordinary putaway rule written from the floor — except in a warehouse marked
  as storing wherever there is room.
- **Replenishment from reserve**: a location marked as reserve fills the pick
  locations of its warehouse before anything is bought; only what reserve
  cannot cover becomes a draft purchase order.
- **Picking**: with the phone's camera, several dispatches in one session
  along each location's **Walk order** number, with progress per dispatch. A
  dispatch may name a zone and take from the shelves under it, splitting each
  line by the product's removal order. **Confirm the location by scan** makes
  picking, receiving and put-away ask for the shelf's label first. A session
  can be handed to a colleague with its scans, and the audit log says who
  took it over, which scans a closed-and-discarded session dropped, and how
  much of a receipt was held back in quarantine and under which reason.
  Before a walk starts, the dispatches that stock cannot cover are listed
  with what was ordered and what is available, and the person starts without
  them or anyway; a pick finishes short, and a skipped pick or receipt line
  is settled, only after someone chose the reason, which decides whether the
  rest is owed on a backorder. Without a scanner a
  dispatch or a session prints a **Pick list** on paper: the lines in the
  same walk order, the location code first, and a barcode of the document.
- **Packing and shipping**: picked goods go into numbered packages
  (`OUT/2026/0042-P1`) with a weight, a packing-slip PDF and a package label,
  downloaded or sent to the label printer; completing a dispatch records its
  carrier and tracking number, typed or read from the parcel label with the
  phone's camera, linked to the tracking page of InPost, DHL, DPD, GLS, Poczta
  Polska, UPS, FedEx or a link template of the organization's own.
- **Start, Board and History**: the Start screen's **To do** lists what needs
  doing — receipts and dispatches, deliveries ordered but not received,
  planned production, counts
  that fell due, put-away tasks, documents waiting for a decision and your own
  tasks — each as one sentence with the button that does it, given to a person
  or taken. A leftover from a short dispatch says whether the stock for it has
  arrived, and the ones that can be issued come first. The Board shows the same
  work in three columns with this week's dock-to-stock time; History tells every completed movement in plain words.
- **Location codes that read like the shelf** (`A-02-01`) for a business, from
  a code template per warehouse, renumbered without losing the sticker already
  on the shelf. **Codes and labels** in the Warehouse menu lists the shelves
  with their codes and prints their labels, and the shelf a scan opens offers
  to print its own.
- **Value tracking**: where the profile asks for it, prices and tax on receipts
  and issues appear in the register and on printouts; what leaves stock is
  costed FIFO from the receipts' cost layers whatever the profile. The
  organization keeps its tax rates in Settings, started from its country's
  standard and reduced rates;
  a product or a category names its rate, so a receipt or a purchase order
  of food and other goods carries both rates without one being typed, and
  states the tax per rate on screen and in print.

#### Around the warehouse

- **Purchase orders** to suppliers, received in part or in full on the receive
  screen, with price lists and reorder rules that turn running-low alerts into
  draft orders.
- **Approvals**: multi-stage workflows that hold purchase orders, warehouse
  documents and equipment check-outs, for everyone or for chosen people and
  roles; granting a document's approval posts it. An equipment check-out
  request names who the asset goes to and until when, and its approval covers
  that hand-out only. A workflow is switched on
  only against the scope it was shown, from the screen and from the API alike.
- **Partners**: suppliers, customers and service providers.

#### Production

- **Bills of materials** for a product: components per batch with a yield
  loss, BOMs used inside other BOMs, process steps, and fixed costs per batch
  (labour, packaging, overhead). Each BOM works out what a unit costs at
  today's rates against a reference price, and the list shows the last
  completed run's unit cost against it — a shop price as a saving, or your
  selling price as a margin.
- **Production runs**: the cost previewed before anything moves, at today's
  average or supplier prices, then completed — the components leave the shelves, the product enters stock at
  what those exact components cost when they came in (FIFO) plus the fixed
  costs, and the quantity actually made and the scrap are recorded. A run can
  be recorded as already made in one step, with what the records lacked left
  as a count to do, or planned for a day, with what is missing offered to the
  shopping list. A completed run is undone from its page while nothing it made
  has been used: the components return to the shelves and batches they came
  from and the product leaves stock.
- **The result by month** on the list of bills of materials — a margin or a
  saving, as the settings name it: the difference between the reference price
  and the cost recorded for everything made (an ingredient nobody priced counts
  as nothing, and its line is marked as uncosted).

#### Kitchen

- **Recipes** with ingredients, steps, a cover photo, servings and tags,
  written by hand, imported from a web page (with an AI connection) or from
  JSON, and kept in collections. Every ingredient says whether it is on the
  shelf — available, similar, not enough, missing, or unknown when its name
  matches nothing or its unit cannot be compared with the shelf's — on which
  shelf and how close to its date; **I can cook** lists the recipes that are
  ready or nearly there.
- **Cooking from stock**: **Take from stock** walks the ingredients, scanned or
  tapped. A tap takes the batch that expires first; scanning a later batch is
  flagged and the earlier one offered, which the cook may decline. Each pick
  can be undone. **Cook step by step** shows one instruction at a time with
  timers. A recipe's availability panel puts what is missing or short on the
  shopping list, in the quantity you are short of (the whole amount where the
  units cannot be compared). With the Production module on, a recipe also
  offers **Cook a batch for stock**, which starts a production order.
- **Estimates read off the ingredients**: nutrition per serving, the cost
  from what the stock cost (else supplier prices, else a price typed on the
  line), and the EU allergens, suggested from an ingredient's name when its
  name field is left, for an ingredient that has none yet, and correctable by
  hand; generic nutrition values and unit conversions per ingredient can be
  overridden by the organization. Allergens, nutrition and the printed recipe
  say in one line that they are suggestions and estimates to check against
  each product's label.
- **A meal planner**: plans of breakfasts, lunches, dinners and snacks with
  each day's carbohydrates, protein, fat and calories, meals dragged between
  days and cooked from stock with **Cook Now**, suggestions ranked by how much
  of the recipe is in stock, what expires within three days, what has not been
  cooked lately and how quick it is, a copy of a plan to another stretch (a plan
  covers at most 14 days, first and last included), and one shopping list for the
  whole plan that adds what the shelves do not cover (an ingredient with no
  product to check against is added in full) and leaves out what is always at
  home.
- **Shopping lists** filled by hand, from recipes and meal plans, or from what
  is running low, and turned into a draft purchase order.
- **Nutrition** from Open Food Facts, with its Nutri-Score shown.

#### Equipment

- **An asset register** for laptops, phones, network gear or any other
  physical thing: serial number, asset tag, category fields, equipment models
  that pre-fill new assets, import from CSV or XLSX, assets added in a batch
  from a list of serials, with a QR label each when the box is ticked, and
  attachments such as invoices and manuals.
- **Check-out and check-in** to a person with an expected return date and a
  handover protocol from an editable template, or to a place the asset
  stands in until it is checked back in; a return marked damaged or needing
  repair puts the asset into maintenance and files a repair entry for it.
  **My Assets** shows each signed-in person the assets checked out to their
  login email, and every asset has a timeline.
- **Maintenance**: repairs, upgrades, inspections, cleaning and other work,
  each with its cost, the technician and the next due date.
- **Attestation campaigns**: people holding assets in a scope get an email with
  a link and, on a public page without signing in, confirm that they still
  have them or report a problem, with reminders and a count of the answers;
  where no email goes, a pending person's link can be copied from the campaign
  page and handed over (a holder with no email address gets no link, and the
  launch names them).
- **What needs attention** on the overview: overdue returns, warranties
  ending soon, warranties already ended and assets in maintenance that nobody
  holds; further down, beside the latest check-outs, the fleet's value for
  administrators and managers, from a straight-line book value per asset
  worked out from its price, purchase date and useful life (an asset missing
  the last two counts at its purchase price only).

#### Analytics

- **Statistics**, always on: a daily health check (expiring, running low,
  the stock's value), an expiry forecast, stock by location and category, cost
  by category and month, and a reconciliation that checks the shelves against the movement journal and
  the quantities the cost history holds against the shelves.
  On a 4-CPU, 8 GB server (the 7 EUR a month class) running the whole stack,
  with 100 000 products, 300 000 records and nearly a million stock
  movements, the statistics answer in under a second and the heaviest
  reports, the stock reconciliation and stock and valuation as of a date, in
  two to three and a half seconds ([the scale report](docs/SCALE_REPORT.md) has the
  figures). The scheduled
  reconciliation does not repeat on every restart.
  The **Analytics** tab, which a small household can switch off, adds alerts
  for forgotten products, missing staples and price spikes, stock age by
  category, slow movers and dead stock, recurring and seasonal products, and a
  spending forecast.

#### Integrations

- **API keys** in their own header, each with the permissions chosen when it
  is issued, starting read-only — for Home Assistant, n8n, Make, Zapier or a
  script.
- **Webhooks**: signed outbound notifications for inventory and warehouse
  events, `document.shipped` among them. An event is recorded in the same
  transaction as the change it describes and delivered afterwards, so a
  change that is rolled back announces nothing and a server that stops
  between the save and the delivery still sends it on restart. That holds
  for storage, category, label, membership and module changes as well as for
  items and documents. The membership events (`user.joined_organization`,
  `user.left_organization`) carry the member as a plain object with `id`,
  `email`, `full_name` and `role`; the password hash is never part of it.
- **Photo recognition**: a product's name, expiry, weight and nutrition read
  from a photograph of its label, through a provider each organization chooses
  — Gemini, OpenAI, Anthropic, any OpenRouter model (Qwen among them), a
  local model through Ollama, LM Studio or vLLM, or any other
  OpenAI-compatible endpoint.
- **A REST API** with OpenAPI documentation (`docs/api/openapi.json`) and one
  documented error envelope (`docs/api/ERRORS.md`).

#### For module authors

- **One door into Core on each side**: `app.core.module_sdk` for the backend
  and `@/module-sdk` for the frontend. CoreAPI — over 30 namespaces of typed
  methods — is what a module calls, and a module installed from outside the
  repository may import nothing else but the public API of a shipped module
  its manifest requires; the install-time safety scan refuses the rest.
- **Product fields come from categories and locations**: there is no separate
  item-type concept, so neither the REST API, CoreAPI nor the module manifest
  has item types, and a manifest declares its categories directly.
- **Events are recorded with the write**: a module that subscribes to a Core
  event receives it only once the change has committed, and one emitted with
  `emit_transactional` survives a crash between the commit and the delivery.
  A subscriber to `user.joined_organization` or `user.left_organization`
  reads the member from `user` as a dictionary (`user["email"]`, not
  `user.email`) and finds only `id`, `email`, `full_name` and `role` there;
  it never receives the account row.
- **Checked contracts**: snapshots of CoreAPI, the module SDK and the frontend
  module interface fail the build on any change that is not purely additive,
  and a deprecated method carries the release that removes it.
- **A module can extend the warehouse**, from this repository or installed
  from outside: its own fields on documents and their lines with slots on the
  forms, a check that stops a document from posting, tasks in To do, a picking
  order of its own, and a column, a filter and an action on the documents.
  [`examples/lot_certificates`](examples/lot_certificates/) demonstrates the
  fields, pre-post check, pick order and document list contributions, and is
  installed and run by the test suite. A module can also keep a delivery
  off locations that are wrong for it — a chilled product off a warm shelf —
  when the putaway rules place it.
- **A module keeps its own tables and migrations**, declares the platform it
  needs (`inventari_min_version`, `manifest_version`) and versions its
  settings, migrating every organization's copy on upgrade.
- **A scaffold** — `make new-module` in this repository,
  `make new-community-module` for a package of its own — and a documented test
  loop for a module developed outside this repository. The worked example is
  `example_widgets`; the guides start at [`MODULES_GUIDE.md`](MODULES_GUIDE.md).
- **English is the only language a module from outside must ship**: any other
  language it covers is optional, and a reader in one it does not cover sees
  the module in English, key by key.

#### Running it

- **Docker Compose** for development, production and the demo; a quick deploy
  guide for a server with a domain, HTTPS through Caddy and backups that run
  from the first night. Tested on Ubuntu 26.04 LTS.
- **Several organizations on one installation**, custom roles and
  permissions, an audit log the application cannot rewrite, and a module
  switch per organization; onboarding asks how the organization works and
  where it sits (the country sets its standard tax rate), switches on what
  fits, and focus mode shows a single module on its own.
- **Memory limits set per host**: `BACKEND_MEM_LIMIT`, `DB_MEM_LIMIT`,
  `DB_SHARED_BUFFERS` and `DB_EFFECTIVE_CACHE_SIZE` (the deployment guide gives
  values for 4, 8 and 16 GB hosts), and a backend worker that has grown
  replaces itself.
- **Stored secrets can move to a new encryption key** with
  `manage.py secrets reencrypt`.
- **Five maintained languages** (English, Polish, German, French, Spanish),
  a phone-first interface and dark mode. **Brazilian Portuguese** ships as the
  first community translation: a language below full coverage, read in
  English for any text it has not got yet, marked as a community translation
  with its share in the language menu, and updated in batches by whoever
  speaks it. Brazilian business use needs NF-e, which is not included; it is
  a module the community could write. English follows the organization's
  country: outside the US dates read day before month and spell the month
  (3 Apr 2026, where a US organization reads Apr 3, 2026) with British
  month and weekday names, on screen and in printed documents.
- **A public demo**: one click gives a visitor an organization of their own,
  already stocked and wiped every night, with a sheet of labels to print and
  scan. Its server logs, which carry visitors' addresses, are held for seven
  days and the privacy page says so.
