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

### Fixed

- A product whose nutrition came from Open Food Facts now counts its calories
  in recipe estimates and in the meal plan's daily totals. They used to go
  missing while its protein, fat and carbohydrates were counted, and the day
  lost its totals altogether.
- A printed recipe whose calories are not known says "Calories unknown" instead
  of "0 kcal".
- Handing an asset back from "My assets" opens a dialog titled and worded for
  the person returning it, and the damaged and needs-repair choices each say
  which repair entry they open. The holder's assignment history prints both
  days and the condition in the interface language, and the organization log
  does the same for the condition of a return.
- The organization log marks the settings a workspace mode writes when it is
  chosen as "Workspace mode default" instead of an update the person made.
- The equipment overview counts a new asset as soon as it is saved, also after
  a batch add, without reloading the page.

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
  cooked lately and how quick it is, a copy of a plan to another stretch whose
  last day falls at most 14 days after its first, and one shopping list for the
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
