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

### Changed

- **Breaking:** the document product search no longer returns `created_at` on a
  stock hit; it returns `added_date`, the day the record was added — the same
  date the product card shows as "Added on", so the picker and the card no longer
  disagree by a day around midnight. A client that read `created_at` reads
  `added_date` instead (a date, not a timestamp). A hit that is the total of
  several interchangeable records now says so with `merged: true`, and the picker
  tells such rows apart by their product's code rather than by the code of one
  record in the group. The `location_id` description now says what the search
  does: a shelf answers with its own records only, a zone also with the shelves
  below it.
- A refused invitation now answers with one sentence that says what to try — use
  the e-mail address the invitation was sent to, or ask for a new one — and the
  sentence is the same for a wrong address, an expired, a used, a withdrawn and an
  unknown code, so it still tells nobody which of them it was. The separate
  "issued for a different address" answer is gone, since it confirmed that a code
  was live. **Breaking:** the refusal code `ORGANIZATION_INVITE_WRONG_EMAIL`,
  listed in `docs/api/ERRORS.md` for 0.11.0, is no longer sent; a client that
  branched on it now receives `ORGANIZATION_INVITE_INVALID`, the code every other
  refusal of an invitation already carried, and should treat the two alike. The
  public link check (`GET /public/invitation/{code}`) keeps answering a dead code
  with a 404 and that same code, but with a sentence of its own that asks for a
  new link, since the check never sees an address.
- An API key's shown prefix is now `inv_live_` and six characters instead of
  eleven, on the API keys page and in the audit log, where it gave away a third
  of the key's random part to anyone allowed to read the log. Existing keys are
  shortened on upgrade and keep working, because a key is never looked up by its
  prefix. Entries already in the audit log keep the longer prefix they were
  written with, since the log cannot be rewritten; they still begin with the
  short one, so a script comparing prefixes should compare the start. To take a
  key's longer prefix out of circulation, issue a new key and revoke the old one.
- A new API key no longer starts with the permission to read the organization's
  details and member list ticked. A script that creates a key through
  `POST /api-keys` without naming any permission now gets a key that cannot read
  `/organizations/my/members` (it answers 403); name `org:read` explicitly to
  keep the old behaviour. The key dialog starts with that permission unticked as
  well.
- Settings has a "People" entry in its sidebar and phone menu that leads
  straight to the members and invitations, which used to sit at the foot of
  General. The webhook dialog lists every event in the interface language and
  groups the events of modules the organization has not enabled apart.
- `GET /items/archived` pages by the last record seen, as the stock movement
  ledger and the audit log do: it answers with `next_cursor`, takes `cursor`
  for the page after, counts on the first page and carries that count, so a
  page deep in a long archive costs what the first one does. Records archived
  at the same instant are ordered by their id, so turning a page no longer
  shows one of them twice and leaves out another. `offset` still answers and
  is deprecated. The archive screens of the product list and of Equipment page
  this way.
- Creating an account — the first one, by invitation or from an approved
  request — signs it in and continues to the app, instead of sending the new
  owner to a sign-in form that asks for the address and password just chosen.
  If the sign-in is refused, the form opens with the address filled in.
- A password-reset link that is spent or expired is refused when the page opens,
  with a link to request a new one, instead of after a new password has been
  typed. The page asks the new open endpoint `POST /auth/password-reset/check`,
  and says it is checking while the answer is on its way. A request refused
  for coming too often from one address no longer calls a good link spent:
  the form stays, and a refused save says to try again later.
  The "this installation does not send email" notice also says that the only
  administrator can reset the password on the server.
- A confirmed document now keeps your own company's name, tax number and
  address and the names of the locations it refers to, as it already kept the
  partner, so a reprint after the company moved or a shelf was renamed shows
  what the original showed. The record a closed stock take leaves in the
  register keeps them too. The layout, the document type's settings and the
  logo are still read when the document is printed, and a document confirmed
  before this change prints the current details. A module that prints its own
  documents through the core print identity can freeze the same block with
  `issuer_snapshot` and `IssuerContext.from_snapshot`.
- **Breaking:** the approve, reject and request-approval routes of documents
  and purchase orders read the note from the JSON request body as
  `{"notes": "..."}`. They no longer read a `notes` query parameter, which
  put a free-text reason where proxies and access logs keep it; a client that
  still sends one must move it to the body, or the note is not recorded.
- The approval queues show a document's net amount and say that it is net, the
  side the approval threshold is set on. They used to show the gross.
- A refusal about a closed period names the month as the period screen does
  ("September 2026"), not "2026-09".
- A multi-node deployment no longer collects a dead member in the event and
  task stream groups for every restart: the stream reaper removes consumers that
  have held nothing for an hour, and a clean shutdown removes the event bus's own
  at once. The reaper also runs once at startup, so a message a crashed node had
  read but not finished is redelivered at once when the replacement starts more
  than a minute later, instead of up to six minutes after the crash.
  `docs/SCALING.md` says what the delay depends on.
- The module store in Settings is now headed "Modules", the name of its
  sidebar entry, and the Statistics settings link carries the module's own
  name instead of "Analytics". Every settings destination reads the same in the
  sidebar and in the heading of the page it opens in all languages. Removing a
  member now asks "Remove <name>?" and says that person loses access at once
  while the records they created stay.
- Equipment attachments and the files attached to a product accept one list
  of file types. The old binary Word format (`.doc`) is refused by both — save
  it as `.docx` — and Equipment now takes `.zip`, as products always have. The
  file pickers on both screens no longer offer `.doc`, which the server refused
  only after the upload. The size limits stay as they were: 20 MB for an
  equipment attachment, 10 MB for a product's.
- **Breaking:** the `/api/v1/ws/notifications` WebSocket takes the access token
  as a subprotocol instead of a `token` query parameter: the client offers
  `bearer` and then the token (`Sec-WebSocket-Protocol: bearer, <token>`), and
  the socket answers with `bearer`. In the address, the token was written into
  the backend's log and every proxy's access log on each connect, and those
  logs outlive it; in a header it travels as it does on every other request. A
  client that still sends the token in the address is refused with close code
  4001 and has to offer the two subprotocols instead.

### Added

- Module authors get three more helpers in the module SDK: `hit_constraint`
  (did this integrity error trip one of the named constraints, by the name the
  driver reports with the message text as fallback), `rows_to_csv` (header and
  rows to CSV text, with every data cell defused against spreadsheet formulas,
  as the built-in exports do) and `utc_now` (the timezone-aware current moment).
- `manage.py user create-admin` takes `--lang` (`en`, `pl`, `de`, `fr`, `es` or
  `pt`) to set the language the account opens in; an unknown code is refused,
  and without it a new account takes the instance default and an existing one
  keeps its own. DEPLOYMENT.md and QUICK_DEPLOY.md say how to use the command
  to get back into an installation without outgoing mail.
- `manage.py user erase <user id>` erases one person's account on a GDPR
  erasure request: it shows whose account it is and asks first (`--yes` skips
  the question), then replaces the address, name and password, closes the
  account and revokes its sessions in one transaction, and reports
  "Nothing was erased" with exit code 1 when a step fails, Redis included.
  It replaces the Python script `docs/GDPR_MANUAL_PROCEDURE.md` asked
  operators to paste. The procedure also says now that the user id the
  journal keeps is pseudonymised personal data, not anonymous, and that
  journal entries naming the person stay only on a legal ground — with the
  SQL to redact them when there is none.
- Module authors can ask `@/module-sdk` whether the signed-in user is the person
  a record names by e-mail address (`useIsSignedInAs`).
- Module authors can page a list the server pages by cursor with
  `useKeysetPaging` from `@/module-sdk`: it keeps the cursors of the pages
  already visited and starts from the first page when the question changes.
- When a recipe's "Add missing", a meal plan's "Generate Shopping List" or a
  list's "From recipes" writes goods that another open shopping list still
  asks for, the answer names them and the list that holds them
  (`on_other_lists`), and the screen says so — in a toast, and on the meal plan
  page in the panel that stays. The lists are still written as asked; nothing is
  merged. Goods in another unit are not matched.
- The name field of a form that creates a product offers the products already
  in the catalogue whose name contains what is typed; picking one writes its
  exact name, which is the match the save attaches the record to. Typing
  "Wax" no longer leaves a second product beside "Soy wax".
- An empty Products list says that products which exist only as a definition,
  such as ones made inside a recipe or a BOM, appear there once they have stock.
- A module's settings schema may mark an option `requires_modules`: the option
  is shown only while those modules are enabled. The recipes option "Register
  production as internal issue documents" uses it, so an organization without
  the warehouse is no longer offered an option that would do nothing.
- `POST /warehouse/documents`, which writes a draft, takes an `Idempotency-Key`
  header as `POST /warehouse/documents/post` does: the same key sent again is
  answered with the draft the first request wrote instead of a second one. A
  request without the header writes a draft each time, as before.
- Module authors can hand an attachment's file picker the types the server
  accepts, `ATTACHMENT_FILE_ACCEPT` from `@/module-sdk`, instead of keeping a
  list of their own.

### Fixed

- Uploading a product picture that only starts like one — a GIF, PNG or JPEG
  header followed by something else — is now refused as unreadable instead of
  being stored and shown as a broken thumbnail. The equipment note beside the
  item actions now calls the action "Return", as the button does.

- `manage.py db stamp-module` now works on a database that a newer version has
  already migrated. `db doctor` refuses to start in that state and prints this
  command as the way out, but the command itself stopped with "Can't locate
  revision" because it first looked up the revision the database recorded, which
  the older checkout has no file for. It now replaces the recorded revision
  without looking it up. The index on `audit_log (organization_id)` is dropped
  by a migration too: the two composite indexes on the journal serve every read
  it did.
- Refusing a partner that already exists now names its type in the reader's
  words ("Supplier", "Dostawca") rather than the stored value `SUPPLIER`, in
  every language, and so does the refusal to confirm an order to a partner that
  is not a supplier. A rename that loses a race for the name no longer ends the
  transaction around it, and a duplicate is told apart by the constraint the
  database reports instead of by text that also quotes the row's values.

- On a phone, the picking and receiving lists show the whole product name and
  the whole batch and location code instead of cutting them: they break at a
  space or a hyphen and inside a code only where it does not fit the column. A
  product name without spaces no longer runs off the edge in the line under the
  scan field or gives the picking summary a horizontal scrollbar.
- The Receive goods, Issue goods and Move goods forms refuse a missing value
  where it is. Receiving without a supplier or customer marks that field and
  says why under it, as the location field already did, and the sentence is no
  longer repeated in the footer or on the phone's start panel, so a screen
  reader announces it once. An error under one field no longer pushes the
  other fields of its row out of line on any of the three forms.
- A request refused for exceeding the general rate limit is answered in the
  request's language: a Polish, German, French or Spanish reader used to get the
  refusal in English, while one refused by an endpoint's own limit already got
  it in their language. Both kinds of refusal now carry `lang` beside `message`.
- `DEFAULT_LANGUAGE` reaches the backend container on both the development and
  the production stack, and is in `.env.production.example`. It used to be read
  only by a backend started outside Docker, so an account created without a
  language — the administrator `manage.py user create-admin` makes without
  `--lang` — started in English whatever `.env` said.
- The symbol list in the document and equipment template editors reads as
  something a template author can use. Examples of record-valued symbols
  (`totals_by_unit`, `packages`, `pick_lines`) show their fields instead of
  Python dictionaries with `Decimal(...)` wrappers, the document examples
  (title, status) are in the editor's language, and the Name hint, the
  unbalanced-HTML message and the description of a category custom field are
  translated instead of falling back to English. `GET
  /warehouse/templates/placeholders` answers in the request language, and a
  custom-field entry of the equipment placeholder lists carries
  `custom_field_label` and `custom_field_categories` beside its English
  description.
- A module that is switched on now says on its store card when a module it
  works better with is switched off, as the card already did before the module
  was switched on. The roles screen names a module with no translation of its
  own, such as one just made with `make new-module`, by the name in its
  manifest instead of its technical identifier.
- The Check Out Asset dialog names an address nobody in the organization uses
  before it saves it, also when the address is pasted and submitted at once.
  The check waited for the typing to pause, and a quicker Enter stored the
  address with no warning ever on screen; such a submit now shows the warning
  and saves nothing, and the next one saves the asset to that address.
- A fault while reading the documents awaiting your approval, or a supplier's
  pricelist for a price suggestion, is now answered as a server error and
  logged with its traceback. The approval list used to come back empty and the
  suggestion fell back to the last purchase price, so a fault looked like
  having nothing to approve, or like the supplier's price.
- A request whose `X-Request-ID` or `Accept-Language` header carries a byte
  outside UTF-8 is no longer answered with a 500. A client's `X-Request-ID` is
  kept only when it is 8 to 64 letters, digits and hyphens, as a UUID or a
  trace id is; any other value is replaced by one the server makes, which the
  response returns as before, because the id is written into every log line
  of the request.
- A "not found" answer is in the reader's language on every endpoint; many
  still answered in English. A module's `NotFoundException` raised without a
  language now speaks the request's language too.
- Closing or reopening an inventory period refuses a month outside 1–12 or a
  year outside 2000–2100 with a 422, instead of closing a thirteenth month.
  Pasted import text is refused with a 422 past the size an imported file may
  have (50 MB).
- The consumption report's two top-ten lists, the products used most and the
  ones whose disposals cost most, put equal products in the order of their
  names. A tie at the tenth place used to be settled by the order the database
  returned the rows in, so the same window could name a different tenth product
  from one reading to the next.
- Importing ingredient data from a file with no usable row — an empty sheet, a
  renamed photo, a bank statement with no name column, a list of numbers — now
  answers with what the import expects instead of a green "0 added" message.
  A file with some good rows still imports them, and the message turns into a
  warning when any row had to be skipped.
- The scanner's Back button now leads to the launcher when the scanner was the
  first screen of the tab — opened by address, through a printed code's link or
  after signing in — instead of doing nothing.
- Refusing an asset's status change from the bulk edit now reads in the language
  of the session (it was always English) and the row carries a machine code, and
  the Polish sentence no longer says "zmienić status z". A refused row of a
  warehouse document import carries its code too, and a database error in a row
  now shows the generic sentence instead of the statement that failed.
- Replacing the photo of a product, an asset or a recipe shows the new picture
  at once. It used to go on showing the old one until the page was reloaded,
  because every cover was kept under the same address. Module authors get
  `cover_leaf` and `cover_leaf_of` in the module SDK to name and read a cover
  file the same way. A photo picked in the product edit sheet is now saved with
  Save changes, and Close drops it like any other edit; it used to be stored the
  moment it was picked and then overwritten by the save.
- The production Content-Security-Policy admits the web worker that shrinks a
  photo before it is sent, so choosing a photo no longer logs a policy
  violation or shrinks it on the page's own thread.
- On an organization seeded before the option words existed, the "Lactose free"
  field of the Dairy and Cheese categories now offers its options in the
  interface language instead of the stored English "No" and "Yes". Options an
  organization wrote itself keep their words.
- The stock-on-a-date report can be narrowed to a product: it has a search
  field, the stock list's "Stock on a date" button carries the search and the
  place you had narrowed to, and the spreadsheet, the printout and the
  `search` parameter of `GET /stock-as-of` follow the same text. Its total and
  counts then speak about the matching products only.
- The "Show inventory value" setting says that it also governs the product
  screens, exports and printouts, not only the statistics overview, and a
  profile that hides stock value no longer shows it for a moment while the
  setting is still on its way.
- Smart alerts state in words how far off an expiry date is ("Expires on
  12.11.2026, in 3 days"), and an alert about a date within the week is amber
  rather than grey. On a phone the expiry forecast tiles sit two across, so no
  label breaks inside a word in any of the six languages, and uppercase labels
  keep their word spaces.
- Two locations can no longer be saved with one name at the same level when two
  people, or a retried request, name them at the same moment: the second is
  refused with the same "already exists at this level" answer a later attempt
  gets. The database now holds the rule too. On upgrade, places that already
  shared a name under one parent keep both: the newer one is renamed with a
  number after its name, for example "Cellar (2)".
- Add Category opens empty, on the product and the equipment category screens
  alike. It used to bring back the last name typed, after a cancel and after a
  save, where saving it again was refused as a duplicate.
- A product's thumbnail goes back to the picture the product has when the server
  refuses a new one, and the same file can be picked again. It used to go on
  showing the refused picture until the form was reopened.
- A product form whose category list could not be loaded says so and offers a
  retry, instead of quietly leaving out the fields the category declares.
- The action sheet opened from a location's products or a scan explains why an
  asset's actions are worded differently, as the product page does. An account
  that may not act on the record no longer gets that sentence on either of them.
- On a document form, a line the price books and past purchases have no price
  for says so under that line. The sentence below the table now speaks only of
  the document having no accounting value: as one sentence for every line, it
  could not be true of two lines in different states.
- Editing a draft return now offers the kind of partner the goods go back to:
  suppliers on the return of a receipt, customers on the return of a delivery.
  The form used to read the partner already on the draft as empty and refuse to
  save, and a return to a manufacturer was refused by the API as well.
- The scan confirmation on a document and the unit question on the item form
  name the unit in the interface language ("szt.", not "pcs").
- The short-pick dialog says "Cancel" like the short-receive one, and the picking
  sheet's main button says "Complete picking", matching "Complete receiving".
- The Polish refusal to finish a document with an open picking or receiving
  session agrees with the number of sessions.
- The answers of `PATCH /documents/{id}/confirm`, `.../complete` and
  `POST /documents/{id}/post` carry `confirmed_by_name` and `completed_by_name`,
  which were `null` until the document was read again.
- Printing a list of labels gives a sheet of rows, three labels across, in the
  preview and in the download alike. It used to be one strip, however long,
  which the dialog shrank into a grey line of bars. The print queue still sends
  a printer its strip.
- Product distribution by location no longer lists archived locations, or a
  container with no records of its own as if it were an empty shelf, and writes
  location and category names as they were typed, so the space in "Rack A-01"
  stays visible.
- A stock take report shows a surplus in blue, like its Overstock tile, not in
  the red of an error beside an amber shortfall.
- Warehouse occupancy no longer suggests a cheese in its search box on every
  profile, and the statistics page no longer calls a warehouse's stock supplies.
- Deactivate on a module's card reads as a button.
- The demo data charges the tax of the organization's country, and none where
  no country is set, rather than Polish VAT on every order and document.
- Equipment, small things a regression pass found: adding an asset opens the
  new asset (a batch opens the asset list) and retiring one keeps you on it;
  the public attestation page says which organization asks and by what day,
  and its confirm texts follow the number of assets still open; an import
  that lost rows says it finished with errors and names the serial numbers it
  skipped as duplicates; an asset in service with an empty log says nothing
  is logged for the service yet; the German screen is "Meine Geräte", and the
  Polish module speaks of issuing (*wydanie*) throughout. The date picker now
  prints a day the way the rest of the application does.
- Tapping a screen for the first time now shows a loading sign at once, inside
  the application's frame, instead of leaving the old screen up for as long as
  the download takes. The very first open of the application shows the product
  name and a loading sign instead of a white page.
- A row of the inventory overview about a date opens the product with its
  expiry date in view; on a phone it was a long way down the sheet.
- On a phone, a purchase order's main action sits on its bar rather than in the
  "..." menu, the new partner sheet keeps Save in view, the statistics tabs fit
  the screen, and the product suggestions open above the keyboard. A line added
  to a shopping list from the replenish suggestions keeps its unit, and the
  analytics tiles say what they count.
- The product search no longer empties itself while you are using it. Its list
  used to close and take your text along on a scroll event when nothing had
  moved, or when the form was still sliding into place as the list opened. It
  now closes only when a scroll moves a box that was standing still, and stays
  under the box while the form settles.
- Warehouse floor papercuts: the carrier typed on the picking summary is
  still there when packing opens; a camera without a torch no longer offers
  the light switch; the lot on the receiving expiry sheet and a product's own
  code on the product form can be read with the camera instead of retyped,
  and the lot sheet no longer opens with the keyboard over the expiry date; a
  correction draft describes each line as added to or removed from stock in
  words, the same way on its line, summary and confirmation; every row of
  the history keeps its columns aligned; and a write-off ends on a write-off
  result instead of "Issued".
- Finishing a stock take right after saving the last count no longer refuses
  with "one product is still uncounted": Complete stock take now waits until
  the saved count is back on the screen.
- Ticking two filter chips quickly on the product list no longer drops the
  first one from the address, which turned it off a moment later.
- The product list keeps its order when you come back to it: the sort is part
  of the address, so Back from a product finds the rows where you left them,
  and a chip ticked in the same moment as a change of sort stays on after Back
  too.
- A product's place on the product list is left blank while its name is still
  on its way, also after a search, another page or a chip changes the rows; it
  used to read "Unknown" until the names arrived. A place whose name cannot be
  loaded still says "Unknown".
- Saving a receipt as a draft again after the answer was lost on the way back
  (a phone changing networks) no longer leaves a second draft behind: the
  answer is the draft the first save wrote.
- A purchase order's approval panel follows the approvals settings: after
  "Admins may approve their own requests" is saved, going back to the order
  offers Approve without a reload.
- The confirmation after saving a module's settings is worded in the interface
  language, and the one after signing in in the language of the screen the
  account opens in, not the device's.
- The notice to an approver names the document, who asked and the net amount,
  in the app and by e-mail.
- Completing a purchase order sends one notice per person; an administrator who
  raised the order used to get two.
- A write-off is weighed against the approval threshold at what the goods cost,
  so one under the threshold raises no approval request and shows no approval
  step or approver on its page. One whose goods have no recorded cost still
  needs the approval.
- A note written when approving or rejecting a purchase order is recorded. The
  screen sent it in the request body and the server read only the query string,
  so it was lost.
- The journal names the custom role an invitation offers, not the built-in level
  under it, and shows a print layout by the name the settings screen gives it.
- Saving a supplier price or a reorder rule without a product now marks the
  product field as required and says so on the field, and a reorder rule whose
  maximum is below its minimum is refused on the Maximum field in plain words.
  On a phone, the reorder rules are cards with their figures and actions in
  view instead of a table that scrolled off the right edge.
- A low-stock alert for a product with no preferred supplier now proposes the
  supplier of its cheapest current price-list entry, and a draft purchase order
  made from it goes to that supplier, instead of reporting "No supplier" beside
  a price the module holds.
- The purchase-order approval warning names the approval threshold when the
  threshold is the requirement left, and a viewer opening the Production or
  Purchase order settings is told that only an administrator can open them
  instead of "You can view this" above an empty page.
- Module settings with a bounded number (such as the equipment warning window)
  answer a value out of range in the app's own language rather than in the
  browser's.
- Locations: an address that is not a location identifier shows the same "not
  found" page as an unknown one, the archive confirmation says that the
  locations inside stay in the lists, an empty location no longer offers a
  button to an empty Products tab, the archived locations are reachable from a
  phone, and Archive and Delete sit at the top of a location's settings. The
  note about hidden locations tells a member who can turn the setting on
  instead of sending them to a page that refuses them.
- Choices drawn by colour alone (the Production settings groups and the
  tracked fields of a location) now report which option is selected to
  assistive technology.
- Equipment categories: deleting one says what goes with it, and the Desktop
  Computer, Network Device and Peripheral presets have icons of their own. In
  Polish the Batches status tabs read as plurals. The AI connections page no
  longer shows its title twice.
- A recipe's page and printout show a dash for a nutrient no ingredient
  measured where the sum would have been 0, as the meal plan does. A rice dish
  where only the chicken had values used to read "Carbs 0.0g".
- "Max batches from stock" on a bill of materials shows ten as 10, not 1E+1.
- The day's activity and History state the stock change of a correction: taking
  one piece off an issue reads "by +1", where it used to read "by −1".
- A generated community module asks for its own read and write permissions on
  every route, and its manifest declares them with the usual default roles.
- A product used up to zero reads "Consumed" in the list and on its page rather
  than "Consumed (Virtual)", and no longer offers "Add 1 unit", which was
  refused after the click. Move brings it back to a shelf.
- Add product shows pieces on its unit button when no unit was chosen, which is
  what the save has always filed such a product as; it used to read "Choose".
- Receive goods and Issue goods can add a supplier or customer that does not
  exist yet without leaving the form.
- A posted receipt says which of its lines have no price: they are left out of
  the totals, and that stock has no recorded cost.
- A dispute note in an attestation names the asset by its serial number when it
  has one, and the public page says what was confirmed beside what was reported.
- The message for a missing approval workflow tells a storekeeper to ask the
  administrator instead of describing the administrator's settings.
- Amounts in a unit that is a word take its plural ("6 bottles").
- An issue dated today can be planned from its page, so that picking can start
  on it without dating it tomorrow first.
- The audit log now writes the quantities and amounts of a production order,
  its completion, a recipe and its ingredient and cost lines, and of an item's
  creation, use, disposal, deletion and restoration, and the low-stock
  threshold of a product, as the exact digits the record holds. They used to
  be saved as rounded decimal numbers, so a production order of 1,234.567 read
  1,234.57 in the log. Saving a value again
  with other trailing digits ("2.50" over "2.5") still writes no entry. Entries
  written before this keep the numbers they were saved with.
- Importing ingredient data from a file the import cannot read, a photo or a
  JSON file that holds no list of rows for instance, now says what the import
  expects: a .json or .csv file with one row per ingredient, in every
  maintained language. It used to repeat the JSON parser's own words.
- Exporting the document register to CSV no longer loads every line, product
  and user of the period into memory: a file of 20 000 documents of ten lines
  takes half a second instead of seventeen and 40 MB instead of 1.2 GB. The
  file itself is the same, still without a limit on rows. Asked through the API
  for a period that ends before it starts, the export answers 400 with a sentence
  saying so instead of an empty file.
- A product name longer than 100 characters can be searched: the search looks
  for its opening, and a failed product search is reported as failed, with a
  button to try again, rather than as "no results". A long name that only
  shares its opening with an existing product can still be added as new.
- A product whose nutrition came from Open Food Facts now counts its calories
  in recipe estimates and in the meal plan's daily totals. They used to go
  missing while its protein, fat and carbohydrates were counted, and the day
  lost its totals altogether.
- A printed recipe whose calories are not known says "Calories unknown" instead
  of "0 kcal".
- Signing in right after creating the first account, joining an organization
  by invitation or finishing an approved request has the address just used
  filled in.
- Pressing a name chip in the location wizard or the new-location sheet no
  longer replaces a name already typed ("Rack A" stays when "Rack" is pressed).
- A purchase order line picked from the catalogue starts from the price the
  product last cost, when it has one, even if none of it is left in stock; a
  price typed on the line is kept, and an order in another currency than the
  organization's proposes none.
- The product label dialog no longer shows "Lot and expiry date" ticked while
  it is disabled for products that have neither, and the explanation of the
  location codes describes the numbering in words rather than printing the
  raw template.
- Handing an asset back, from "My assets" or from the asset's own page, opens a
  dialog titled and worded for the person returning it (the page's button reads
  "Return" too, not the manager's "Accept"), and the damaged and needs-repair choices each say
  which repair entry they open. The holder's assignment history prints both
  days and the condition in the interface language, and the organization log
  does the same for the condition of a return.
- The organization log marks the settings a workspace mode writes when it is
  chosen as "Workspace mode default" instead of an update the person made.
- On a phone, the buttons of the sheet that issues an asset stay in view at the
  foot of the sheet instead of ending below its edge until the form was
  scrolled, and the notice that an approval is needed sits beside them.
- The equipment overview counts a new asset as soon as it is saved, also after
  a batch add, without reloading the page.
- The new production dialog writes the unit the way the rest of the app does
  ("szt." rather than "pcs"), and its hint about the recipe's batch no longer
  ends in two full stops. The audit log names the unit a product template was
  created with the same way.
- The stock changes a production run writes, and the ones its reversal writes,
  carry a reason in the interface language instead of an English sentence,
  followed by the number of the run, in the audit log and in the item's history.
- A recipe's page prints its name once, as the page title; the card under it
  keeps the batch yield and the default badge, and the product made is named
  under the title only when it is called something else.
- The onboarding card for working with a single module now names Production,
  so a person who came to make things can find it.
- Saving two partners with the same name, or the same code, at the same moment
  now refuses the second one with the usual "already exists" message instead
  of failing with a server error.
- A recipe ingredient typed by hand whose name has accented letters ("Ryż") now
  finds the product on the shelf ("Ryż 1 kg") instead of reading as missing.
- The expiry date picker starts with a week, two weeks and a month, so fresh
  food no longer needs the calendar.
- The two date chips on the products list, "expiring soon" and "expired", no
  longer stay on together and show an empty list: turning one on turns the
  other off.
- Statistics count stock rows as records instead of pieces, name the products
  without a category in the reader's language, list the fullest places first
  and leave out the system's consumed, loss and production places.
- The meal plan dialog that has no plan yet now says the recipe is added to the
  first meal of the new plan at once, and closing the "Take from stock" dialog
  no longer marks the recipe as cooked.
- The built-in layouts in the document templates' preview are named in the
  reader's language ("Standard layout", "Pick list"), as the print-layout
  picker names them, instead of "Standard Template" in every language.
- An organization template keeps an `alt`, `title` or `class` whose text
  begins with "Data:" — the Polish label for a date — on the printout and in
  the editor's preview; the sanitizer used to drop it as if it were a `data:`
  link. A logo uploaded as WebP now prints through `{{ issuer.logo }}` instead
  of leaving an empty image.
- The error details a broken screen offers to copy into a bug report no longer
  carry the token of the link that opened the page: on a password reset,
  invitation, registration or equipment attestation page the token reads
  `redacted`, so a report pasted into a public issue tracker hands nobody a
  live link.
- Inventory, location and equipment dialogs say what failed and what they
  need: creating a location, saving a stock alert, a bulk edit, changing a
  batch's status and freeing a label name the write that could not be done
  when the server gives no reason, instead of "Unknown error" or "Something
  went wrong". The location wizard no longer suggests a name already taken at
  that level by a location a module owns or one in the archive. Bulk edit's
  Apply waits until a field is ticked, the bulk Retire question says before
  you answer that a checked-out asset is not retired, and the archived label's
  sheet calls the deletion reason by its name rather than "Status". Saving an
  empty service entry marks every missing answer in the app's language,
  instead of stopping at the title with the browser's own message.
- Stored photos load on an instance that serves the app straight from the
  frontend container, without the bundled Caddy in front. That container's
  nginx answered every `/uploads/…` file ending in `.jpg` or `.png` with its own
  404 instead of asking the backend; a PDF attachment came through. An
  instance behind Caddy was not affected, since Caddy sends `/uploads/*` to the
  backend itself.

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
