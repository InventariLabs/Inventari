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

- A new community module package can be handed to an AI coding agent.
  `module new-community` now writes an `AGENTS.md` into the package — what a
  module may import, the five maintained languages, migrations the package
  owns, the purpose card, tests and the command that checks the package before
  install, with links to the full guides at the platform's version — and a
  `CLAUDE.md` that points at it. MODULE_QUICKSTART.md has a section on
  building a module with an agent: what to give it, which checks refuse its
  mistakes and how to check the result before installing it.

### Fixed

- The dead-end notice on an approval request no longer blames the requester for
  the stage's dead end. A stage listing them beside people who cannot see
  approvals names only those people, and the access step names only them; an
  administrator is offered the self-approval setting as another way out. The
  notification sent for the same case no longer calls a stage naming several
  people "the person".

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
