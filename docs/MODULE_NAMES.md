# Module Names — Single Source of Truth

This document is the agreed table of **user-visible names** in the five maintained
languages (Portuguese (Brazil) is a community translation: it is not in the tables, and a key
it lacks reads in English). It exists so that a name can be checked against something authoritative instead
of being guessed per pull request. Naming disputes are settled here, not in code.

It covers three layers of names: **modules** (the marketplace/launcher entries, below),
**workspace modes** (the product profiles a user picks during onboarding — see
"Workspace mode names") and the **domain vocabulary** — the words the core screens use for
what is stored, where, how much, and what happens to it (see "Domain vocabulary"). The
first two follow the same shape: i18n is the source of truth, the backend field is a
fallback, and the technical identifier is never a label.

## Rules

1. **Single source of truth for the visible name: the i18n key `modules.<name>.name`**
   in `frontend/src/i18n/locales/*/modules.json`. The key is indexed by the **backend
   module name**, never by a synonym. The one exception is `core`, whose entry is
   `modules.core.title` (the audit journal's name for it) and carries no description.
2. **`display_name` from the backend manifest is only a fallback** — for community modules
   the frontend does not know at build time. For a first-party module, a missing i18n key
   is a bug, not an acceptable state.
3. **`launcher.title` is not a second module name.** It must be identical to
   `modules.<name>.name`; enforced by `frontend/src/i18n/__tests__/moduleNameParity.test.ts`.
4. **Searchable name = visible name.** App Store search matches against the translated
   label and description, plus the technical name and the manifest originals.
5. **README reflects this table** — it is not a parallel source of names.

Technical module names (`maker`, `recipes`, `stats`, …) are **identifiers**, not labels:
permission namespaces (`maker:*`), i18n namespaces, route paths (`/maker/production`),
registry keys, migration directories and the installed-modules record (`backend/data/community_modules.json`) all hang off them.
They never change as part of naming work.

## Name table

Every key of the `modules` catalog has a row: the fifteen shipped module directories,
`partners`, `core`, `items` and the three always-on features `locations`, `categories` and
`announcements`. Those three have a catalog `name` and nothing else — no store card, no
description — because the audit journal prints the module list an organization starts with
and must name each key from this catalog, not from a vocabulary of its own.

| Technical name | en | pl | de | fr | es | One-sentence description |
|---|---|---|---|---|---|---|
| `core` (virtual) | Home & Kitchen | Dom i Kuchnia | Haus & Küche | Maison & Cuisine | Hogar y cocina | Fridge, Pantry, and basic products. Always on; not a marketplace module. |
| `items` (always-on) | Inventory | Inwentarz | Inventar | Inventaire | Inventario | The products domain behind the inventory screens; always on, named by the inventory launcher card. |
| `locations` (always-on) | Locations | Miejsca | Lagerorte | Emplacements | Ubicaciones | Where stock lives; named by the journal only, no store card. |
| `categories` (always-on) | Categories | Kategorie | Kategorien | Catégories | Categorías | How products are grouped; named by the journal only, no store card. |
| `announcements` (always-on) | Announcements | Ogłoszenia | Ankündigungen | Annonces | Anuncios | Notices to members; named by the journal only, no store card. |
| `api_keys` | API Keys | Klucze API | API-Schlüssel | Clés API | Claves API | Programmatic access via REST API keys. |
| `approvals` | Approvals | Zatwierdzenia | Genehmigungen | Approbations | Aprobaciones | Multi-stage approval workflows for critical operations. |
| `warehouse` | Warehouse | Magazyn | Lager | Entrepôt | Almacén | Scan with your phone's camera or a scanner to receive, issue, move and count stock; the numbered documents are written in the background, with putaway rules. |
| `equipment` | Equipment Tracking | Śledzenie sprzętu | Geräteverfolgung | Suivi des équipements | Seguimiento de equipos | Track IT and physical assets with lifecycle management. |
| `example_widgets` | Example Widgets | Przykładowe widżety | Beispiel-Widgets | Widgets d'exemple | Widgets de ejemplo | Reference module demonstrating Inventari module patterns: manage simple widgets with a name, color, and quantity. Hidden from the store. |
| `maker` | Production | Produkcja | Fertigung | Fabrication | Fabricación | Production runs, bills of materials (BOM), and cost rollup. |
| `nutrition` | Nutrition Info | Wartości odżywcze | Nährwertinformationen | Informations nutritionnelles | Información nutricional | Display nutritional data and ingredients from Open Food Facts. |
| `partners` (virtual) | Partners | Partnerzy | Partner | Partenaires | Socios | Manage suppliers, customers, and service providers for B2B workflows. |
| `printing` | Label Printing | Druk etykiet | Etikettendruck | Impression d'étiquettes | Impresión de etiquetas | Generate and print labels for products and locations. |
| `purchase_orders` | Purchase Orders | Zamówienia zakupu | Einkaufsbestellungen | Bons de commande | Órdenes de compra | Create and track purchase orders with suppliers. |
| `recipes` | Recipes | Przepisy | Rezepte | Recettes | Recetas | Create and manage recipes with ingredient tracking. |
| `shopping_lists` | Shopping Lists | Listy zakupów | Einkaufslisten | Listes de courses | Listas de compras | Create and manage shopping lists with automatic suggestions. |
| `stats` | Statistics | Statystyki | Statistiken | Statistiques | Estadísticas | Advanced consumption analysis and waste tracking. |
| `stock_takes` | Stock Takes | Inwentaryzacja | Bestandsaufnahmen | Inventaires | Conteos de inventario | Periodic inventory checks to verify stock accuracy. |
| `vision` | Photo Recognition | Rozpoznawanie ze zdjęć | Fotoerkennung | Reconnaissance photo | Reconocimiento fotográfico | Reads a product's name, brand and expiry date off a photo of its label. Switched off, adding a product loses its photo tab and nutrition tables have to be typed in. |
| `webhooks` | Webhooks | Webhooki | Webhooks | Webhooks | Webhooks | Outbound HTTP notifications about events in your workspace. |

### What these names are NOT

- `warehouse` is shown as "Warehouse" (pl "Magazyn", de "Lager", fr "Entrepôt", es
  "Almacén"): the module is where stock is received, issued, moved and counted, and the
  numbered documents are what it writes in the background. The word was the Storage
  container's until the container became **Location** (see "Domain vocabulary"), which is
  what freed it — one concept, one word (UI_GUIDELINES §14.2). It still names a
  *family* of documents when it qualifies one ("warehouse documents" in a sentence), and the
  module's own list of records keeps the plain word ("Documents" / "Dokumenty": sidebar item,
  breadcrumb, mobile bar, page title), because it names the records, not the module. The
  description must not promise purchase orders, which live in `purchase_orders`.
  `frontend/src/modules/warehouse/__tests__/sidebarLabel.test.ts` keeps the module's name off the list's labels. The module's
  tab for per-location settings is "Codes and labels" ("Kody i etykiety"), not
  "Locations", so that the word names one place in the app only; Configuration › Putaway
  links to the same screen.
- `maker` is **not** "Maker" — that is the code name. Four of five languages had already
  translated it away; English "Production" completes the set. Not "Manufacturing" (factory-scale connotation), not
  "Production & BOM" (redundant, breaks narrow tiles).
- `vision` is **not** "OCR Scanning" — the module recognizes products in photos with a
  multimodal model; "OCR" describes a document scanner and sells the module below its
  value. If OCR is mentioned at all, it is one capability in the description.
- `approvals` in Polish is **Zatwierdzenia**, not "Akceptacje".
- `equipment` in Polish is **Śledzenie sprzętu**, not bare "Sprzęt".
- `stock_takes` in Polish is **Inwentaryzacja**, without the technical-name parenthetical —
  an English identifier in the Polish UI is a leak, not a hint.
- `recipes` (**Przepisy**) is **not** `maker`'s production input — see the glossary below.

## Workspace mode names

A **workspace mode** is a product profile (`app.core.product_profiles.PRODUCT_PROFILES`) —
the set of modules, seeds, theme and branding a user picks in the onboarding wizard and can
change later in Settings → My modules. Three ship with Inventari. Their names are the second
layer of user-visible naming and follow the module rules above, restated here for the
profile registry:

1. **Single source of truth for the visible name: the i18n key `profiles.<id>.name`**
   (and `profiles.<id>.description`) in `frontend/src/i18n/locales/*/common.json`, indexed
   by the **profile id**, never by a synonym.
2. **`name` / `description` on the backend `ProductProfile` are only a fallback** — for
   profiles outside this distribution that the frontend does not know at build time. For a
   shipped profile, a missing i18n key is a bug, not an acceptable state. The fields stay in
   the registry; they are not deleted once i18n exists.
3. **The profile id is never a label.** `food_home`, `equipment_wms` and `clean_core` are
   identifiers: `Organization.active_profile_id` in the database, the CLI
   choices, the `seed_<id>` function names and the permanent-delete blocklists all hang off
   them. Renaming a mode never touches them.
4. **Every consumer resolves the label through `useProfileLabels`** — no component reads
   `profile.name` or `profile.description` directly. Enforced by
   `frontend/src/i18n/__tests__/profileNameParity.test.ts`.

### Mode table

| Profile id | en | pl | de | fr | es |
|---|---|---|---|---|---|
| `food_home` | Food & Home | Dom i jedzenie | Essen & Zuhause | Alimentation & Maison | Alimentación y hogar |
| `equipment_wms` | Equipment & Warehouse | Sprzęt i magazyn | Geräte & Lager | Équipements & entrepôt | Equipos y almacén |
| `clean_core` | Custom | Własny | Benutzerdefiniert | Personnalisé | Personalizado |

One-sentence description per mode (English row; the other four languages translate it):

| Profile id | Description (en) |
|---|---|
| `food_home` | Track food inventory, cold storage, and shelves. Includes recipes and shopping lists. |
| `equipment_wms` | Track IT assets and equipment with warehouse procurement — purchase orders, receiving, check-out/in, maintenance logs, and warranty alerts. |
| `clean_core` | No industry preset — a neutral base you shape yourself. |

### Decisions behind the third mode

The first two modes name a domain. The third has none — it names the *absence* of one, and
that is what the label and the description have to say.

- **The name is "Custom" / "Własny"**, not "Clean Core". An adjective reads naturally
  under the "Workspace mode" heading, where the two neighbours are domains. Rejected:
  "Custom settings" — on the *Settings* page a second "settings" duplicates the context and
  suggests a screen rather than a mode. Held in reserve if the bare adjective ever proves
  too thin in a card: "Custom setup" / "Konfiguracja własna".
- **The description no longer promises a reset.** The old text said "Build your own
  configuration from scratch", but switching to this mode keeps every manually enabled
  module (`backend/app/services/profile_switch_planner.py`, `manual_kept`) and never overwrites data: its seed is insert-only, so it adds only the rows that are
  missing. The
  description must be true both in the onboarding wizard *and* on a running installation,
  so it describes the starting point, not an erasure. What exactly changes on a switch is
  the job of the "What will change" panel, not of the description.
- **The neutral mode deliberately has no wordmark subtitle.** `food_home` renders
  "Inventari for Home" and `equipment_wms` "Inventari for Business"; `clean_core` renders
  the plain "Inventari" wordmark. A mode defined by having no domain has nothing to append,
  and inventing one ("your way") would claim an identity the mode does not have. This is a
  decision, not an omission — `branding` stays `None` on the profile and carries a comment
  saying so.
- **The neutral mode does get its own palette.** It used to declare no `theme`, which meant
  it fell back to the default accent — the same emerald `food_home` declares explicitly, so
  the two modes were visually indistinguishable. `clean_core` now owns an amber ramp.
  Amber also carries a warning meaning elsewhere in this app (cascade disables in the
  profile-switch diff, warranty and maintenance alerts). The two never share a screen
  region, and the profile theme repaints `accent-*`/`primary-*` while those warnings use
  literal `amber-*` utilities, so they do not collide mechanically; the overlap is
  deliberate.
- **`launcher_categories` stays empty** for `clean_core`. The map is an *override*, so an
  empty one means the mode states no opinion about grouping and each module lands in the
  section it declares for itself. Grouping is an opinion about a domain, and a mode named
  "Custom" holds none.
  An empty map does not render the Launcher as a flat list: since `resolveProfileCategory`
  gained its fallback chain, the sections still render, built from module metadata. The
  flat grid is a mobile layout, unrelated to the profile.

### What these names are NOT

- `clean_core` is **not** "Clean Core" on screen. "Core" is our architecture word
  (AGENTS.md, "domain-neutral Core"), not a user concept — shipping it as a label is the
  same class of leak as `maker` was before it became "Production". "Clean" additionally
  promised a cleaning that never happens.
- The workspace mode is labelled "Workspace mode" (Polish *tryb pracy*) wherever a label
  names it. "Profile" in this product means a user profile and a document profile, and the
  word survives in code and API paths. The onboarding status messages, the launcher's
  workspace switch and the permanent-delete setting all say "workspace mode" now.

## Domain vocabulary

The core screens talk about a handful of concepts over and over: where things are kept, what
is kept, how much of it, and what happens to it. Each concept has **one winning word** below.
The drift this table settles was never a single slip. The words are layers from the
application's successive purposes — a fridge, an IT desk, a warehouse — and a new screen
copied from an old one brings its layer's word along: one storage wizard said "storage",
"location" and "existing location" within a few lines, the stock register called reserved
quantity "spoken for", and a page held "places" where its sibling held "storages".

Rules:

1. **One concept, one word, per language.** A word in the "Retires" column is not written
   again for that concept — in a new string or in a changed one.
2. **The table is the decision record.** Naming disputes are settled here, in the same
   commit that changes the strings (see "Changing a name").
3. **English is gated, the rest is reviewed.** `frontend/scripts/check-vocabulary.mjs`
   (`npm run check:vocabulary`, part of `make check-frontend`) fails a retired word in a new
   or changed English string and holds the strings that already used one in
   `frontend/scripts/vocabulary-baseline.json`; an entry shields only the exact text it holds.
   A word list does not carry across languages (Polish "magazyn" is retired as a place, yet it is
   the name of the Warehouse module and stays in "stan magazynowy"), so de/fr/es/pl are held to
   this table by review and by the per-concept tests named in the last column.
4. **Identifiers do not follow.** `Item`, `zone`, `/inventory/items`, the `items` namespace
   and `consume`-named keys stay; the visible word is the table's.

| Concept | en | pl | de | fr | es | Retires | Why |
|---|---|---|---|---|---|---|---|
| A place stock is kept — the top level a user opens (`Cold Storage`, `Receiving`) and every node inside it (`Shelf A - Top`, `Bay 3`) | **Location** | Miejsce | Lagerort | Emplacement | Ubicación | storage (as a name for it), place, room, zone, spot, warehouse, shelf (outside shelf life and named shelves); fr stockage; pl magazyn, lokalizacja, miejsce przechowywania; de Standort | The app had five words for one thing — Storages, storage location, target location, Locations (equipment) and Warehouse. The tree already treats the levels alike; the word does too. "Warehouse" became the name of the module that moves stock. |
| The thing that is stocked | **Product** | Produkt | Produkt | Produit | Producto | item, article, przedmiot | The sidebar said Items over a subtitle that said products (§14.3). |
| A product's stock row in a location, counted across modules | **Record** | Rekord | Datensatz | Enregistrement | Registro | entry, row (in prose) | Boundary with *asset* written down in "asset vs equipment vs record". |
| The physical quantity | **On hand** | Na stanie | Bestand | En stock | En existencia | in hand, current stock (as a column) | It is the figure the ledger posts against (ADR-022). |
| Quantity set aside for something | **Reserved** | Zarezerwowane | Reserviert | Réservé | Reservado | spoken for, promised, committed, held | "Spoken for" appeared nowhere else, and "reserved" is the column header beside it. |
| What may still be given away | **Available** | Dostępne | Verfügbar | Disponible | Disponible | free, spare, left (as a column) | Always on hand minus reserved. |
| Taking quantity off stock (any reason) | **Remove** (from stock) | Zdejmij (ze stanu) | Entfernen | Retirer | Retirar | consume, take off, deduct, abbuchen, quitar | The dialog asks a reason, so the act is wider than "consumed". |
| The reason or the resulting status when it was used up | **Consumed** | Zużyte | Verbraucht | Consommé | Consumido | used up, spent | It is one reason among several (used, expired, damaged), and the ledger's own code. |
| Putting a product somewhere else | **Move** | Przenieś | Verschieben | Déplacer | Mover | relocate, shift, transfer (as a verb) | One action, one name (§14.4). |
| One line of the register of what moved | **Movement** | Ruch | Bewegung | Mouvement | Movimiento | transaction, transfer (as a noun) | The register is "Stock movements". |
| The internal-transfer *document* | **Transfer** | Przesunięcie (MM) | Umlagerung | Transfert | Transferencia | — | A document type of the `warehouse` module, not a verb: the exempt use of the word. |
| The product-profile a user picks | **Workspace mode** | Tryb pracy | Arbeitsbereich | Mode d’espace de travail | Modo de espacio de trabajo | profile (in the UI) | Settled above, under "Workspace mode names". |

What the table does not claim:

- **Words that name a different act keep their word.** A production run *consumes* its
  ingredients (`maker`): the run posts a ledger line of its own and no reason is asked. The
  gate skips the `maker` catalog for the consume rule only, on purpose. "Decimal places" and "the only place a line can be
  re-parented" are idiom, not the container; the gate exempts both.
- **Warehouse** is the name of the `warehouse` module, and "warehouse documents" names its
  family of documents; the vocabulary gate exempts that compound, the workspace-mode name
  "Equipment & Warehouse" and the module's own name in the curated keys of that rule, and only those: a
  bare "warehouse" meaning a place is still flagged. A field that picks a place is
  **Location** ("From location" / "To location"; pl "Z miejsca" / "Do miejsca"), never
  "storage location", "source location" or "target location" as a label. "Poland — warehouse", a numbering preset of the `warehouse` module, and the
  `place` strings of the equipment, stats and stock-take modules sit in the baseline until
  their own screens are swept. The baseline is the list.
- **What the gate reads, and what stays with review.** Every row of the table has a rule except
  where the retired word has a second life as ordinary English. *Item/article* is a rule with the
  compounds that are not the stocked thing exempt (line item, list item, menu item, shopping list
  item); *entry/row* only as "stock entry" and "product row"; *held* only as quantity held or held
  for; *shift* only with a product, stock or record as its object; *transfer* only as a verb
  with one of those objects; *free/spare/left* only as a bare column header or as "free/spare stock", "free/spare quantity" or "free/spare qty";
  *used up* anywhere, and *spent* unless it is money ("total spent", "spent on", the
  cost-analysis column); *shelf* anywhere except shelf life, shelf-stable, a named shelf
  ("Shelf A", "Top Shelf") and the bare type "Shelf"; *profile* anywhere except a user's own
  profile and the `warehouse` module's document profiles. A bare "entry", "row", "transfer" or "left" is prose, and review reads it.
  The strings that break a rule today sit in the baseline; the list is the sweep that is left.
- **"In stock" stays.** It answers "is there any?", which "on hand" does not: a product
  with quantity on hand but all of it reserved is on hand and not available.
- **Examples a user might type** ("Living room", "Zone A", "e.g. Warehouse operator") are
  data, not vocabulary.
- **French is Emplacement.** The container used to be Entrepôt, which is now the module's
  name; the register's filters and the permission labels no longer say "Stockage".
  German is Lagerort (the module is Lager) in every catalog and in the server's messages and PDF labels —
  Standort is retired, including inside the equipment module; Spanish Ubicación (the module is Almacén), Polish
  Miejsce (the module is Magazyn).

## Glossary of contested terms

### recipe vs BOM (przepis vs receptura)

Two different objects share accidental vocabulary today:

- **recipe / przepis** — the culinary input of the `recipes` module (kitchen).
- **BOM / receptura** — the production input of the `maker` module (manufacturing).

Rules:

- The English `maker` UI uses exactly **one** term: **BOM**, expanded at first on-screen
  use as "bills of materials (BOM)", as the launcher card and the module description do. The words "formula" and "production recipe" do not
  appear in `maker` copy.
- Polish `maker` UI uses **receptura**, consistently, in opposition to **przepis**
  (`recipes`). German, French and Spanish follow the same one-term-per-module rule.
- Rescue adjectives like "culinary" in `maker` copy ("Based on a culinary recipe") are a
  smell of this collision — once the production object is called BOM, they are unnecessary.
- Technical names stay: the `/maker/recipes` route, `recipe_service.py`, `RecipeCard`,
  `useMakerRecipeCatalog`. Those are identifiers; users never read them.

Open caveat (recorded, not decided): Polish "receptura", like English "formula", implies
mixing rather than assembling. If an assembly vertical (e.g. bike kits) arrives, Polish
may need "lista materiałowa". The przepis/receptura pair works for the verticals the
product serves today and stays.

### asset vs equipment vs record (zasób vs sprzęt vs rekord)

The `equipment` module names three different sets, and until the decision below was
written it named them with four interchangeable nouns (pl: zasób, sprzęt, rekord and
urządzenie — one screen, `/equipment/locations`, showed three of them at once). The module-level name
(above) is unaffected; this entry settles the vocabulary **inside** the module.

The three sets and their words per language:

| Set | en | pl | de | fr | es |
|---|---|---|---|---|---|
| The one tracked thing (added, edited, returned, held, assigned) | asset | zasób | Gerät | actif | activo |
| The module and its collection as a whole (titles, categories, models, permissions, the cross-module badge) | equipment | sprzęt | Ausrüstung / Geräte | équipement / matériel | equipamiento / equipo |
| A thing standing in a storage location, counted across every module's things | record | rekord | Datensatz | enregistrement | registro |

Rules:

- **The individual word (asset/zasób/…) names the tracked thing on every surface**, staff
  and public alike: forms, toasts, the My-Assets descriptions, attestation e-mails. A
  returned thing is "this asset", never "this equipment".
- **The domain word (equipment/sprzęt/…) names the module and its collections**:
  dashboard and page titles, category/model names, permissions, settings, the import
  title, and the badge that marks a location row's origin. German and French keep two
  natural domain words (Ausrüstung/Geräte, équipement/matériel); both are listed, both are
  legal — the role is the rule, not a single word.
- **Polish names the act of handing an asset over wydać, and the record of it wydanie.**
  The button, the bulk action, the tab, the history and the empty states all say it;
  *przypisany do* stays only as the label of the field that names the holder, a state
  and not the act. The English "tag" is not used: the identifier is *numer inwentarzowy*.
- **German names the thing Gerät.** It was Anlagegut, the accounting word for a fixed
  asset — and the module is explicitly not an asset register for accounting. The employee
  asked by e-mail to confirm they still have a laptop read a finance term, on a page that
  elsewhere called the same laptop an Artikel. Gerät is the everyday word, the one the
  attestation e-mail already used, and it shares Anlagegut's grammatical gender, so every
  sentence kept its articles. The domain keeps Ausrüstung and the plural Geräte (as in
  Geräteverfolgung). Words retired this way are listed under `retiredWords` in the map and
  counted per catalog file, so none of them returns.
- **A location's contents are counted as records**, because the count spans every
  module's things, the equipment module's own included — renaming it to the module's word
  would be narrow, and at a delete-refusal outright misleading (the locations-row unification settled this for
  the row messages; this entry keeps it and writes the boundary down). The badge beside the
  count still says the domain word: the count says *how much of everything*, the badge
  says *which module this row's origin is*.
- `locations.view_assets` ("Show the assets kept at this location") is the boundary in
  action, not an exception: it links into the module's **own** filtered list, so it speaks
  the module's individual word — the counts next to it speak "records".
- **Frozen feature names are not vocabulary**: the My-Assets screen is My Assets / Mój
  sprzęt / Meine Geräte / Mon matériel / Mi equipo, and stays so — four of five languages
  chose the domain word for the screen a holder sees (German a plural, as its other screens
  are), and a feature name is a name, not a set reference. Strings that *reference* the screen must use its real name in that
  language (pl „Mój sprzęt”, de „Meine Geräte“, fr « Mon matériel », es «Mi equipo») — not a
  back-translation of the English one.
- **Kind names are exempt**: `categories.codes.*` ("Urządzenie sieciowe", "Inny sprzęt",
  "Other Equipment") name kinds of things, not sets, and keep their natural words. The
  same applies to enumerations ("Track IT assets, equipment, and other physical items").

The measure: cross-family consistency over the whole catalog is **not** structurally
checkable (the locations-row review measured both existing checks looking inside
single families), so no gate promises that. What exists instead is the curated map the task named
as the only defensible premise — `frontend/src/modules/equipment/vocabulary.json` (roles,
word stems, curated key lists, exemptions) — enforced by
`frontend/src/modules/equipment/__tests__/vocabulary.test.ts`: curated individual keys
carry the individual word and no other, feature-name references use the real screen name,
location counters keep the cross-module word, and Polish says *przypis…* only on the
curated holder-field labels and on a label (etykieta) assigned to an asset. Widening the measure means curating
more keys into the map, not loosening a heuristic.

### The `maker` orders tab

The tab opening the production-order list is labelled **Runs / Zlecenia** (de Produktionsläufe,
fr Ordres de fabrication, es Órdenes de producción) — not "Production"/"Produkcja",
because that repeats the module name and is less precise than the page title below it
("Zlecenia produkcyjne"), and not "Orders", which in this product means Purchase Orders.
The route stays `/maker/production`.

## Changing a name

### A domain word

1. Edit the row in the vocabulary table, with the retired words, and get it reviewed.
2. Change every visible occurrence in all five `locales/*/` and `modules/*/i18n/*.json`
   catalogs of the screens the concept appears on. Where a per-concept test pins the word
   (`storageVocabulary`, `productVocabulary`, `movementDirectionVocabulary`), it follows.
3. Add the new losers to `RULES` in `frontend/scripts/check-vocabulary.mjs`, with a test line
   in `check-vocabulary.test.mjs`, and refresh the baseline only with `--write-baseline`.
4. Keep `README.md` and `docs/USER_GUIDE.md` on the same words.

### A module name

1. Edit the row in the module table and get it reviewed (this file is the decision record).
2. Update `modules.<name>.name` / `.description` (`core`: `title` only) in all five `modules.json` files and the
   module's own `launcher.title` (where it has one) in `frontend/src/modules/<module>/i18n/*.json`.
3. Update `display_name`/description in `backend/app/modules/<module>/manifest.json`
   (fallback only — keep it aligned with the English row).
4. Update the module table in `README.md`.
5. Run `moduleNameParity.test.ts` — it enforces rules 1–3 mechanically.

### A workspace mode name

1. Edit the row in the mode table and get it reviewed.
2. Update `profiles.<id>.name` / `.description` in all five `common.json` files.
3. Update `name`/`description` on the profile in `backend/app/core/product_profiles.py`
   (fallback only — keep it aligned with the English row).
4. Leave the profile id alone. Renaming it is a data migration, not naming work.
5. Run `profileNameParity.test.ts` — it enforces the rules above mechanically.
