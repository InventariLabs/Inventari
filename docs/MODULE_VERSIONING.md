# Versioning a Module

Two numbers live in a `manifest.json`, and they answer different questions:

| Field | Question it answers |
|---|---|
| `version` | How far along is *this module*? |
| `inventari_min_version` | What does it need from *the platform underneath it*? |

Keeping them apart is the whole point. A module cannot express "I am finished"
and "I run on anything from 0.8.0 up" with one number, and the two facts move
independently: a module can mature for months without needing anything new from
the platform, and a one-line change can raise its floor overnight.

## `version` — the module's own maturity

### The ceiling: no 1.0.0 while the platform is on 0.x

The public surface of a module is the platform's extension API. A module that
declares 1.0.0 is promising stability it does not control — the ground it
stands on can still move. So while `backend/pyproject.toml` says `0.x`, no
module in this repository reaches `1.0.0`.

This is enforced for the modules shipped here:
`backend/tests/unit/test_module_versions.py` fails the build if a manifest
claims 1.0.0 or above while the platform has not. It reads the store cards as
well, so a module without a manifest — partners, whose card is built in
`backend/app/api/modules.py` — is held to the same ceiling. The test is written
to fail once the platform reaches 1.0.0, so that the change lifting the ceiling
deletes it on purpose.

Nothing stops a community module from numbering itself above 0.x: the platform
checks only that `version` begins with three numeric parts, and says nothing about
the level. The reasoning is offered, not imposed.

### The level within 0.x

A number that means "how complete does this feel" means nothing to anybody
else. The modules in this repository are placed by four signals a stranger can
check from the repository and its issue tracker:

1. **Review cycles closed** — the strongest signal. A module whose defects were
   found by a review, fixed, and then checked again counts for more than one
   that was only fixed, because somebody went back and confirmed the fix held.
   What a stranger can check is what such a cycle leaves behind: tests that pin
   each defect that was found and, for fixes made after the first public
   release, their entries in `CHANGELOG.md`.
2. **Defects still open** — how much is known not to work, as reported in the
   issue tracker. A module with a list of open defects is not mature, however
   many cycles it has been through.
3. **Test lines against source lines** — a ratio, not a count. Absolute numbers
   only say how big the module is.
4. **A complete wrapper** — permissions declared in the manifest, migrations
   the module owns, a five-language catalogue.

Roughly, that gives:

| Range | What it takes |
|---|---|
| `0.9.x` | Several closed review cycles, nothing substantial open, tests at least at parity, complete wrapper |
| `0.7`–`0.8` | Heavily built and exercised, but defects remain open or fewer cycles are closed |
| `0.5`–`0.6` | Complete and tested, not yet through a review cycle |
| `0.3`–`0.4` | Small or partial surface |
| `0.1`–`0.2` | A stub, or a worked example that demonstrates part of the extension API |

The numbers in this repository were calibrated three times before the first
public release: on 24 August 2026, because the previous ones correlated with
nothing; on 17 October 2026, by the same four signals, to confirm what the
first pass set; and on 2 November 2026, on the release commit itself, before
the numbers went into the store listing. From the second calibration on they
only go up.

### Record of the 2 November 2026 calibration

Every module the repository ships was measured again: the fifteen with a manifest
(the store lists fourteen of them; `example_widgets` is a reference module and
has no card), and partners, whose card is built in `backend/app/api/modules.py`.
The tree measured is the release commit `246a05d4e`, the commit the publication
export was taken from. The public history is a single squashed commit, so that
hash names the private source the numbers were read from; the published tree is
the same tree, and the counts can be repeated on it.

How each signal was read, so it can be repeated:

- **Review cycles** — the only signal with no mechanical count; read from the
  tests that pin a defect a review found (the changelog names fixes only from
  0.11.0 on, so the readings come from the tests). This calibration searched the
  module test files for review-found wording. It found such a note in the
  equipment tests (fixes dated to the review of 22 and 23 September), in the
  warehouse tests (a total that was wrong while reviewing the PDF localisation
  work) and in the example-widgets permissions test (three holes found in one
  review). The search does not reproduce the October readings, so the other
  readings are carried forward, not re-derived.
- **Open** — what the issue tracker holds against the module that day: its
  bug-typed items, and open defects filed as findings whose titles name the
  module's area, read from the titles of the open items. Plus four counts from
  the tree: untranslated refusals raised through refusal exceptions in
  `backend/app/core/refusal_sentences_baseline.txt`, untranslated plain
  `ValueError` sentences in `backend/app/core/value_error_sentences_baseline.txt`
  (both ledgers are debt, and each row gives the two counts as "refusals" and
  "value errors"; a module that names neither has none in either ledger), commit
  sites that do not leave the transaction to the caller in
  `backend/app/core/transaction_ownership_baseline.txt`, and the query errors a
  screen never reads, which the frontend gate
  `frontend/scripts/check-query-error-read.mjs` reports. The frozen functions
  in `frontend/scripts/function-baseline.json` are counted alongside.
- **Tests to source** — test lines against source lines. Backend: the module's
  own `tests/` directory and the tests under `backend/tests/` whose file name
  carries the module's name (partners, which has no module directory, counts its
  core files: its router, model, schema, services and `core_api` facade). Frontend:
  the unit specs under `frontend/src/modules/<module>/`; end-to-end specs under
  `frontend/tests/e2e/` are not in the ratio. The module's migrations are left out
  of the source lines.
- **Wrapper** — permissions declared in `manifest.json`, migrations the module
  owns, and the five-language catalogue under its `i18n/`. Every module has the
  five backend languages (de, en, es, fr, pl); some also carry pt.

What changed since 17 October. The ledgers shrank where the debt was paid down:
the refusal ledger has no entries at all, where October counted refusals in
recipes, shopping lists, stock takes, vision, equipment and stats; value errors
fell in recipes (43 to 9) and warehouse (58 to 12). The transaction-ownership
baseline is empty, where October counted commit sites in warehouse, purchase
orders, api keys, webhooks, partners, approvals and nutrition; the allowlist of
legal owners holds no module entries, so those sites were fixed rather than
reclassified. One failed-load site is reported by the query-error gate, in
recipes. Open work grew in the tracker: approvals and maker both gained open
defects since October, and the two items the October record named for them are
still open or not shown closed (see their rows). Test-to-source ratios moved by a
few tenths in most modules; nutrition's backend ratio is higher because the
backend tests named for it are counted under this method, and October's count of
those is not known. Every version and `inventari_min_version` is the same as in
October; the wrapper change the October row named is that `printing` now declares
its `printing:agent` permission. **Nothing was lowered and nothing was raised.**

| Module | Version | Review cycles | Open on the day | Tests to source | Wrapper | Decision |
|---|---|---|---|---|---|---|
| `warehouse` | 0.9.0 | several closed | 0 untranslated refusals and 12 value errors; 0 commit sites in the baseline; 4 bug-typed items and 5 other open defects (receiving, picking, locations, documents); 9 frozen functions; 0 unread query errors | 2.53x backend, 1.07x frontend | complete | **Unchanged.** Keeps 0.9.0 on its closed cycles and its complete wrapper. Its open list is still long, including a locations list that counts records below their ancestors, so the 0.9 condition "nothing substantial open" is not met |
| `equipment` | 0.9.0 | several closed | 0 refusals and 1 value error; 0 commit sites; 4 frozen functions; 1 bug-typed item and 5 other open defects (borrower and checkout screens, attachment deletion, an import answering 500, a location delete guard); 0 unread query errors | 2.21x, 1.27x | complete | **Unchanged.** Keeps 0.9.0 on its closed cycles. The open list is not shorter than in October, so nothing is lowered and nothing is closed |
| `recipes` | 0.8.0 | some closed | 0 refusals (14 in October) and 9 value errors (43 in October); 1 unread query error (a tags panel that shows an empty list when its request fails); 4 bug-typed items and 2 other open defects; 7 frozen functions | 1.82x, 0.95x | complete | **Unchanged.** Its debt fell sharply, but defects remain open, which the 0.8 row describes |
| `purchase_orders` | 0.8.0 | some closed | 0 refusals, 1 value error; 0 commit sites in the baseline (6 in October); 0 bug-typed items and 3 other open defects (a 500 on concurrent reads of a fresh organization's settings, placeholders that print nothing in a custom template) | 1.95x, 1.20x | complete | **Unchanged.** Fewer open items than in October, still more than a 0.9 allows |
| `approvals` | 0.7.0 | some closed | 0 refusals, 0 value errors, 0 commit sites, 0 unread query errors; 3 bug-typed items and 3 other open defects. The one bug October named, the 404 console error from a workflow's waiting count on delete, is still open | 1.63x, 1.55x | complete | **Unchanged.** Candidate for 0.8.0 is not met: the listed bug is open, and the list has grown (see below) |
| `maker` | 0.7.0 | some closed | 0 refusals, 0 value errors, 0 commit sites, 0 unread query errors; 4 bug-typed items and 5 other open defects, including the three October named (see below) | 2.48x, 0.92x | complete | **Unchanged.** Candidate for 0.8.0 is not met (see below) |
| `stock_takes` | 0.6.0 | one closed | 0 refusals (5 in October), 0 value errors (8 in October); 1 bug-typed item (a false orphaned-navigation warning when the module is off) and 2 other open defects (Draft and Start states and cyclic schedules without UI; no edit screen) | 2.08x, 1.36x | complete | **Unchanged.** One closed cycle, own migrations |
| `webhooks` | 0.6.0 | one closed | 0 refusals, 2 value errors; 0 commit sites in the baseline (4 in October); 2 bug-typed items (integration papercuts) and 1 other open defect (the webhook card's layout and its breaker-recovery spec) | 2.38x, 1.24x | no declared permissions | **Unchanged.** Still no declared permissions |
| `partners` | 0.5.0 | none of its own | 0 refusals and 0 value errors (its refusals travel through the catalogue); 0 commit sites in the baseline (the import sites counted in October are no longer in it); 0 bug-typed items and 1 other open item | 2.08x, 1.03x | no declared permissions, no migrations (its tables are core tables) | **Unchanged.** Placed on the ladder on its own |
| `shopping_lists` | 0.5.0 | none | 0 refusals and 0 value errors (6 and 2 in October); 0 bug-typed items and 2 other open defects (report overlaps in the preview; a stock failure naming the list) | 1.60x, 0.90x | complete | **Unchanged.** Complete and exercised, never audited |
| `stats` | 0.5.0 | none | 0 refusals and 0 value errors (2 refusals in October); 0 bug-typed items and 1 other open defect (a date built in a hardcoded order) | 2.45x, 1.09x | no migrations of its own to complete | **Unchanged.** Complete for what it does |
| `printing` | 0.4.0 | none | 0 refusals and 0 value errors; 0 bug-typed items and 1 other open defect in the print templates | 1.37x, 1.84x | complete: `printing:agent` is now declared, which October's row listed as missing | **Unchanged.** Small surface, as October read it. Its wrapper gap is closed, so this is the one row where a raise to 0.5 is arguable; the surface reading is judgement and is left as it stands |
| `nutrition` | 0.4.0 | none | 0 refusals, 0 value errors, 0 commit sites (1 in October); 0 bug-typed items and 1 other open defect (nutrition sums per meal-plan serving). The product-lookup-order bug October named is not among the open items found | 2.16x, 0.70x | no declared permissions, no endpoints, no migration revisions (`migrations/` holds only `env.py`) | **Unchanged.** Partial surface |
| `api_keys` | 0.3.0 | none | 0 refusals, 0 value errors, 0 commit sites in the baseline (4 in October); 0 bug-typed items and 2 other open defects | 2.06x, 1.06x | no declared permissions | **Unchanged.** Small surface |
| `vision` | 0.3.0 | none | 0 refusals (3 in October), 0 value errors (1 in October); 0 bug-typed items and 1 other open item (wording) | 1.89x backend; the frontend module has one 25-line source file and no specs | no migrations | **Unchanged.** Two endpoints; its weight sits in the core LLM subsystem |
| `example_widgets` | 0.2.0 | one review-found note in its permissions test (three holes found in one review) | nothing | 1.52x, 1.38x | complete | **Unchanged.** A worked example of part of the extension API; the 0.1–0.2 row describes it whatever the review note says |

**Approvals.** October's one open item was the 404 console error after deleting a
workflow. It is still open: the delete confirmation still calls the waiting-count
hook for the workflow it is deleting, and that hook is enabled for any workflow id,
so nothing in the code has changed the behaviour. The open list has grown since
October with a dead-end verdict that judges only the first waiting stage, a
request accepted for a target that does not exist, a gap in the self-approval
rule, and papercuts on the workflow screens.
The 0.8.0 condition ("the day the last bug is fixed") is not met.

**Maker.** October named three items. (1) The flaky "New formula" spec is still
open in the tracker, and nothing in the tree shows it fixed. (2) A product
created in a BOM staying invisible on the product list until it is stocked: no
tracker item with that wording was found, open or closed, and no test or change
shows a BOM-created product listed without stock; it is treated as open. (3) One
role word used two ways in the module settings notice: the notice now reads
"administrator" in both of its sentences, and the module-settings test pins both
sentences, so this one is fixed. Two of the three are not shown closed, and the
open list has grown (a shortage-warning spec failure, production-order audit
quantities, a batch of making papercuts, among others). The 0.8.0 condition is
not met.

For a module you write yourself, the ladder matters less than the habit behind
it: whatever you use as a signal, be able to answer "why 0.6 and not 0.8?" with
something checkable.

## `inventari_min_version` — the platform floor

This is the oldest platform version the module is **known** to run on. Not the
oldest it might run on, and not the one you happened to have installed.

```json
{
  "name": "warranty_tracker",
  "version": "0.3.0",
  "inventari_min_version": "0.9.0"
}
```

### What the platform does with it

At discovery, `_validate_manifest` compares the floor against the running
platform version (`backend/pyproject.toml`, read by
`app.core.version.get_platform_version`). A module that needs more than the
installation has **does not load**:

- it is recorded as rejected, with the reason in words —
  `Module 'warranty_tracker' requires Inventari >= 1.2.0, current version is 0.11.0.`
- the reason is available through `module_registry.get_rejected_modules()`
- the rest of the installation comes up around it

That is deliberately better than the alternative, which is a module that
imports fine today and reaches for a name that does not exist yet later, in
front of a user.

The floor is read from the raw JSON as well. `ModuleManifest` refuses fields
it does not know, so a manifest written for a newer platform would otherwise
fail with pydantic's "Extra inputs are not permitted" before the floor is ever
compared. When the strict parse fails, `ModuleManifest.load` looks at
`inventari_min_version` in the raw file first: a floor above the running
platform is reported as `requires Inventari >= X`, and only a manifest whose
floor is satisfied gets the field-level error.

### `manifest_version` — the shape of the file

`manifest_version` (an integer, default `1` when omitted) says which shape of
`manifest.json` the file is written in. This platform reads
`SUPPORTED_MANIFEST_VERSIONS` from `app/core/module_manifest_schema.py`, which
is `1`. A manifest that declares another value is refused with a sentence that
names the versions this platform reads
(`declares manifest_version 2, which this platform does not read (it reads: 1)`),
whether or not it also carries fields this platform does not know.

### `module.yaml` and `manifest.json` carry some of the same facts

A community package has two descriptors, on purpose. `module.yaml` is read by
the installer before any file is copied and is covered by the package
signature; `manifest.json` is read by the registry at every start. Both carry
`name`, `version`, `inventari_min_version` and `requires`, and both apply the
same name rule (`^[a-z][a-z0-9_]*$`, `MODULE_NAME_PATTERN`). Keep the two in
step when you edit one: `module new-community` writes them in agreement, and a
test (`test_manifest_floor_and_version.py`) pins that.

The floor protects forward only — it says nothing about the platform
**removing** something a module already uses. Removals are announced
instead: deprecated `core_api` surface is registered in
`app/core/_core_api_deprecations.py` with a replacement, a reason and a
`removal_release`, and a unit test fails the build once that release
ships (the same machinery `_event_deprecations.py` runs for events).
Before a release that removes registered surface, bump every affected
module's `version` and — if the module builds against a replacement —
raise its `inventari_min_version` to the release that carries it.

**A retirement has one spelling: `.. deprecated::`.** Prose does not count.
A `core_api` docstring reading "(legacy API)" with "Prefer `x`" underneath
retired a method in every way a reader could tell — and in none the registry
guard could, because that guard matches the literal token. The method then
had no deadline, no entry, and a green build over both. So the rule is
mechanical rather than a matter of judgement: a method that is going away
says so with the token and gets a registry entry with a date. The guard
(`backend/tests/unit/test_core_api_deprecations.py`) reads a method's docstring
in two ways, and an author should know which is which:

- **The first paragraph** is the method's own description. Any retiring word
  there is refused: `legacy`, `deprecated`, `obsolete`, `superseded`, "will be
  removed", "no longer supported".
- **Every later paragraph** is read for retiring *phrases* only: "is
  deprecated", "are deprecated", "is obsolete", "is being removed", "will be
  removed", "to be removed", "will be retired", "superseded by", "no longer
  supported". A sentence of that shape says the method is going away, wherever
  it stands, so it is refused with the method named.

What the guard deliberately lets through below the first paragraph is a bare
word. A legacy *data* shape still being read, or a historical field label, is
ordinary prose about something other than the method, and
`decrypt_for_module` and `get_current_rate_async` say exactly that. Keep such
sentences free of the phrases above ("rows written before the rename carry the
old shape" rather than "the old shape is deprecated"). If a sentence has to use
one of the phrases about something else, the method goes into `_PROSE_EXEMPT`
in that test with the reason, not into a narrower rule. A `.. deprecated::`
block is the registered spelling and is never read as prose, so its own
"will be removed in …" line is fine.

The install also scans packaged community modules for calls to deprecated
`core_api` methods (`validate_deprecated_core_api` in `app/cli/module_validator.py`,
run from `app/cli/module_packaging.py`). It names each call with the release that
removes the method, as a warning: the install is not refused for it, so the author
learns the deadline at install time instead of at the next restart.

### Leaving it out

The field is optional. An empty or absent value means *no constraint*, and the
module loads on any version. That is the honest answer for a module nobody has
actually placed against a floor — it is not a shortcut, it is a different
statement, and it is what every module that predates the field says.

### When to raise it

Raise it when the module starts using something the older platform does not
have: a new `core_api` facade, a new helper in `app.core`, a new extension
point. The floor is a claim about the module's dependencies, so it moves with
them and not with your own release schedule.

Do **not** raise it every time the platform releases. A floor of "whatever came
out last week" makes the field useless: it stops describing what the module
needs and starts describing when its author last looked at it.

A worked way to find the answer: for every platform API the module imports,
find the commit that introduced it and the platform version current at that
commit. The newest one is your floor. That is how the numbers in this
repository were set — thirteen of the fifteen modules this repository ships import something
that arrived after the platform reached 0.9.0, so they declare `0.9.0`;
`nutrition` and `stats` import nothing newer than the 0.8.0 consolidation and
declare `0.8.0`.

## Shipping the new version to an installation

Raising `version` is half of it. The other half is what an installation does
with the new package, and for a long time there was no answer: installing over
a tracked module was refused, and the refusal said to uninstall first — which
ran the module's default `on_uninstall`, an Alembic downgrade to base. The
documented route from v0.1 to v0.2 went through `DROP TABLE`.

```bash
python manage.py module upgrade ./warranty_tracker
python manage.py module upgrade https://github.com/you/mod.git --rev v0.3.0
```

`module upgrade` verifies the package's signature the way an install does,
replaces the module's files rather than copying over them (so a file v0.3
deleted stops running), runs the module's own migrations, and leaves every row
in place. The version in `module_installations` is deliberately *not* updated
by the command: it is what tells the next boot that a bump happened, which is
what makes `on_upgrade(old_version, context)` run — from the new version's
code, once per installation.

So the two halves of a release line up like this:

| In the package | On the installation |
|---|---|
| `version` raised in `module.yaml` and `manifest.json` | `module upgrade` copies the files and runs the migrations |
| a new migration under `migrations/versions/` | applied by that command, before any restart |
| data that has to be reshaped, not just migrated | `on_upgrade`, on the next restart, with the old version in hand |
| nothing else | the tables and their rows are untouched |

Uninstalling is the other direction and it is not a downgrade: it removes the
module's code and **keeps its data**, printing what stays behind before it asks.
Dropping the tables is a separate, explicit `--drop-data`, confirmed by typing
the word `data` — or skipped with `--force`, which exists for unattended
scripts and says so in the output before anything is destroyed. Full description in
[`MODULES_GUIDE.md`](../MODULES_GUIDE.md#uninstall-a-community-module).

## A manifest with both, to copy

<!-- validated: manifest.json -->

```json
{
  "name": "warranty_tracker",
  "version": "0.3.0",
  "inventari_min_version": "0.9.0",
  "display_name": "Warranty Tracker",
  "description": "Track warranties and service dates for equipment.",
  "icon": "shield-check",
  "module_type": "community",
  "requires": ["items"],
  "capabilities": ["database"]
}
```

The manifest schema is strict (`extra='forbid'`), so a typo in a field name is
a rejection, not a silently ignored line. Run
`python manage.py module schema` to export the full JSON Schema for your
editor, and `python manage.py module validate --module <name>` to check one
module.

## See also

- [`MODULES_GUIDE.md`](../MODULES_GUIDE.md) — the full `manifest.json` reference
- [`MODULE_CAPABILITIES.md`](MODULE_CAPABILITIES.md) — what `capabilities` may contain
- [`MODULE_NAMES.md`](MODULE_NAMES.md) — the approved display names, in five languages
