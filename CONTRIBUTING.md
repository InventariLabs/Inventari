# Contributing to Inventari

First of all — **thank you for considering a contribution!** 🎉

Inventari provides ready-to-use inventory applications and a shared core for
building your own. This guide covers contributions to the platform and the
modules maintained in this repository. Every contribution, big or small, helps
make it better for everyone.

**Building your own module?** Start with [Module Quick Start](MODULE_QUICKSTART.md).
It includes a separate-package path for a module you develop and distribute
from your own repository.

## 📋 Table of Contents

- [Code of Conduct](#-code-of-conduct)
- [How Can I Contribute?](#-how-can-i-contribute)
- [About the Contributor License Agreement](#-about-the-contributor-license-agreement)
- [Setting Up the Development Environment](#-setting-up-the-development-environment)
- [Development Workflow](#-development-workflow)
- [Writing Modules (Plugins)](#-writing-modules-plugins)
- [Translations](#-translations)
- [Coding Standards](#-coding-standards)
- [Submitting a Pull Request](#-submitting-a-pull-request)
- [Reporting Bugs](#-reporting-bugs)

---

## 📜 Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/); the text is in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). By participating, you agree to be respectful and constructive. Harassment, discrimination, or toxic behavior of any kind is not tolerated.

---

## 🙋 How Can I Contribute?

### 🐛 Report Bugs
Found something broken? Please [open an issue](https://github.com/InventariLabs/Inventari/issues/new?template=bug_report.md). Include:
- What you did
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Docker version, browser, Inventari version)

### 💡 Suggest Features
Have an idea? [Open a feature request](https://github.com/InventariLabs/Inventari/issues/new?template=feature_request.md) or [start a Discussion](https://github.com/InventariLabs/Inventari/discussions).

### 🔧 Fix an Issue
Check [issues labeled `good first issue`](https://github.com/InventariLabs/Inventari/issues?q=is%3Aopen+label%3A%22good+first+issue%22) — these are great entry points for new contributors.

### 🧩 Build a Module
The **module system** is the most impactful way to contribute. You can add entirely new functionality without modifying core code. See [Writing Modules](#-writing-modules-plugins) below.

### 🌍 Add a Translation
We use `i18next` with JSON translation files. If you speak a language that Inventari doesn't support yet, you can add it! See [Translations](#-translations).

### 📖 Improve Documentation
Good docs save hours of debugging. Improvements to README, DEPLOYMENT, API docs, or inline code comments are always welcome.
[`docs/README.md`](docs/README.md) classifies every document in that directory —
which are external guides and which are technical reference — so a new one
belongs in its table, and a link from here or from the README is what makes it
findable.

---

## 📜 About the Contributor License Agreement

**You keep the copyright to your work.** Signing the CLA does not transfer
ownership of your contribution — you continue to hold full rights to it and
can use it in any other project, and what the project receives is a license,
not a deed.

Why a CLA exists here, said plainly: Inventari publishes a free, open-source
edition and **sells commercial licenses** of the same product alongside it.
The CLA is what allows your contribution to be included in both. Without it,
your work could only ever go into the AGPL edition, and every third-party
line in a commercially licensed build would have to be teased apart again.

Two things come with that. The first is a promise the project makes in
public; the second is simply how it already works:

- **The community edition stays free software.** It remains under an
  OSI-approved copyleft license (AGPL). Selling commercial licenses of the
  same code is how the project funds itself; it does not turn the community
  edition proprietary, and this document is the project's public commitment
  that it never will.
- **Trivial contributions need no signature at all.** A typo fix, a broken
  link, whitespace, an obvious one-line fix with no design decision, a
  translation correction — say in the pull request that you consider it
  trivial. A maintainer looks at the change and, if they agree, applies the
  `cla: trivial` label, which waives the signing requirement; you cannot apply
  it yourself. Pushing new commits afterwards, or reopening the pull request,
  removes the label, and the maintainer decides again. The full definition of "trivial" is in
  the [CLA](CLA.md#6-trivial-contributions).

The full [Contributor License Agreement](CLA.md) is short and worth reading
before you decide anything. Signing happens once per GitHub account — one
comment on your first pull request — and every later PR is recognized
automatically.

---

## 💻 Setting Up the Development Environment

### Prerequisites
- Docker & Docker Compose
- `make`, `git`, `curl` and `openssl` — the bootstrap generates `.env` secrets with `openssl` and verifies the running app with `curl`
- Node.js 26+ (both frontend images and ci.yml run 26; vitest 5, the test runner, refuses anything older than 22.12)
- Python 3.14+
- `uv` (Python package manager — `curl -LsSf https://astral.sh/uv/install.sh | sh`)

The path is developed and tested on Linux. On Windows it runs under WSL2 —
where `make` and `openssl` live — and macOS is untested.

### Clone & Start

```bash
git clone https://github.com/InventariLabs/Inventari.git
cd Inventari

make setup-hooks   # pre-commit gates — run once after clone
make dev-up
```

`make dev-up` is the one-command bootstrap — there is no `.env` to write first.
It generates a development `.env` with fresh secrets, builds the containers, runs
core and module migrations, seeds **system** data, creates the default admin
account, and waits until the app answers before reporting success. Sample items,
suppliers and a warehouse hierarchy are a separate step: `make db-seed-demo`.
Run `make help` to see all available commands.

`make setup-hooks` installs the pre-commit gates that run before every commit
(see [Making Changes](#making-changes)). If the `pre-commit` command is not
already on the machine it installs it first — `uv tool install pre-commit`
when `uv` is there, which the list above requires anyway, then `pipx`, then
`pip install --user` — so a clean clone needs nothing that is not already in
*Prerequisites*. They call into the running stack
(`docker compose exec -T backend …`), so with the stack stopped a commit fails
with a message about a service that is not there — start the stack first.

If you would rather write `.env` yourself, note that `dev-up` generates one only
when the file is absent — so you own all of it, including `SECRET_KEY`,
`FERNET_SALT` (`openssl rand -hex 32` each) and `DEBUG=true`. The placeholders in
`.env.example` are refused outside debug mode and the backend will not boot.

The app will be running at:
- **Frontend**: http://localhost:5173
- **API**: http://localhost:8005/docs (Swagger UI) and http://localhost:8005/redoc
- **Mailhog** (the development mailbox — every email the stack sends lands here): http://localhost:8025

The two API pages are served only with `DEBUG=true`, which `make dev-up` writes
into the `.env` it generates; with a `.env` of your own that says
`DEBUG=false` they answer 404. The same schema is in the tree as
[`docs/api/openapi.json`](docs/api/openapi.json), ready to import into Postman
or Insomnia without a running stack.

### Opening it in a dev container

`.devcontainer/devcontainer.json` attaches your editor to the running `backend`
service: the backend source at `/app`, the repository root — this file, the
Makefile, README — at `/repo`, read-only. It cannot start the stack itself,
because the lifecycle command runs *inside* that image, which has neither
`make` nor the docker CLI. So the order stays the one above — `make
setup-hooks` and `make dev-up` on the host first — and the container opens on
a workspace that is already there.

---

## 🔄 Development Workflow

### Branches
`dev` is the integration branch and the repository's default — a clone lands on
it, and that is what you branch from and what your pull request targets. `main`
is the release branch; nothing is pushed to it directly.

```bash
git checkout dev && git pull
git checkout -b feature/recipe-module
git checkout -b fix/expiry-date-timezone
git checkout -b docs/improve-deployment-guide
```

**Never commit directly to `dev` or `main`.**

### Making Changes

Write the test first, then the code — tests are the specification here. While
you work, run **only the file you are touching**: the test you are writing, and
the file covering the code you just edited. Narrow the selection rather than
the suite:

```bash
# One backend file (-n is the number of parallel workers)
docker compose exec backend uv run pytest -n 4 tests/integration/test_auth_api.py

# One frontend spec
docker compose exec -T frontend npx vitest run src/modules/recipes/components/AllergenPicker.test.tsx
```

The pre-commit hook installs with `make setup-hooks` and, on every commit,
**checks** the whole tree (`ruff format --check`/`ruff check`, the mypy
baseline, prettier, eslint, the architecture and contract checks and the
licence-report check) — it never rewrites a file,
so do not run those checks by hand in front of it. When it rejects a commit
for formatting, run `make format` (backend and frontend) or `make frontend-format` (frontend
only), then
`git add -u` and commit again.

The same `make setup-hooks` installs a commit-message hook. A message is read
like a comment by everyone who later meets the change, so it is written in
prose: a subject of about 72 characters (a prefix such as `fix(scope):` is
fine), a blank line, and a body that says why the change was needed when the
subject alone does not. *Commit messages* in [`AGENTS.md`](AGENTS.md) has the
full rule and what the hook refuses.

**Test workers.** `-n` is the number of parallel pytest workers, each with a
test database of its own. Prefer a number to `-n auto`, because the
containers have no CPU limit and `auto` takes every core on the host.
`python3 scripts/test-workers.py pytest` prints the number for your machine
— read from its cores and the memory free right now, capped at 12 — and the
`make` test targets, CI and the Playwright config (`… playwright`) all ask
it. An override still works: `make test-coverage PYTEST_WORKERS=2`. After
changing the script, `python3 scripts/test_test_workers.py` (also part of
`make lint`) runs its budgets against synthetic cgroup files.

The full suite belongs to the branch, once, before it leaves:

```bash
make test-coverage                                          # backend suite + coverage floors
docker compose exec -T frontend npx tsc --noEmit            # type check (the hook does not run it)
docker compose exec -T frontend npx vitest run --coverage   # frontend tests + coverage floors
make lint                                                   # when the branch touches backend/ (checks the hook skips)
make check-frontend                                         # when the branch touches frontend/ (build, frontend gates)
```

Do not push if that gate fails. CI reports only once the branch is pushed, so
the local gates are the ones that count for your branch.

### Generating Database Migrations

If you change any backend models:
```bash
make db-migrate m="add recipe table"
# read the file it names before applying it
make db-upgrade
```

`make db-migrate` compares the models with the database and writes what
differs; with no model change it writes nothing and says so. Read the
generated file before `make db-upgrade`: autogenerate cannot tell a renamed
column from a dropped one and a new one, and a data change it never sees is
written by hand (`alembic revision -m "<message>"`). Indexes a migration builds
by hand, such as trigram searches, are listed in
`backend/app/core/autogenerate_scope.py` so autogenerate leaves them alone.

### Release rhythm

A minor release goes out every two weeks, on a Monday, whatever has landed
on `dev` and passed its gates by then. A change that breaks a client, a module
or an installation ships only in a minor release, is marked **Breaking** in
`CHANGELOG.md` and says what the affected party must do. A patch release
(`0.12.1`) is cut only for a security fix, data loss or an upgrade that
breaks; nothing else waits for one. The maintainers cut the release: they
turn `## Unreleased` into the version's section, bring the version numbers
(listed in `AGENTS.md`, "Changelog") to it, add the release database below
and push `main` and the tag.

### Upgrading from a released database

A migration that passes on an empty database can still stop an installation
that has been used: a backfill that assumes a column is empty, a constraint
added over rows that break it. So every release leaves behind the database it
puts on disk — the schema with the rows the first run and the demo seed write —
as `backend/tests/fixtures/release_databases/v<version>.sql.gz`, and
`backend/tests/integration/test_a_released_database_upgrades_to_head.py` restores each
of them, upgrades it to head (core and modules) and compares the result with
the models. When that test fails on your migration, fix the migration, never
the snapshot: the snapshot is what somebody's server already holds.

Each release adds its own snapshot. It is cut on the release commit — every
migration of the release in, the tag not yet made, so the tag carries the
snapshot — against a running development stack, whose own database, uploaded
files (local or in a bucket) and demo inbox are not touched:

```bash
make release-db-snapshot   # writes v<version>.sql.gz for the version in pyproject.toml
git add backend/tests/fixtures/release_databases
```

The test refuses a version in `backend/pyproject.toml` without its snapshot.
A snapshot stays for as long as an installation on its release may upgrade
straight to the newest one. [SECURITY.md](SECURITY.md) supports only the
latest release and sends everyone older to it, so old snapshots are kept; one
goes only when that path itself ends — a release that requires an older
installation to pass through it first, named as such in SECURITY.md — and then
every snapshot older than that release goes in the same change.

---

## 🧩 Writing Modules (Plugins)

Contribute a module here when it belongs with the applications maintained in
this repository. To develop and distribute a package independently, use the
separate-package path in [Module Quick Start](MODULE_QUICKSTART.md).

### Quick start

```bash
make new-module
# Prompts for a name, then generates backend + frontend scaffold automatically.
```

Read **[MODULE_QUICKSTART.md](MODULE_QUICKSTART.md)** for the complete development and testing steps.

### What gets generated

- `backend/app/modules/{name}/` — a working copy of the reference module: router, service,
  table and migration, permissions, journal entries, integration tests
- `frontend/src/modules/{name}/` — React page, i18n files, types
- the module's name on `REPO_SHIPPED_MODULES` (`backend/app/core/module_safety.py`) and in the
  catalog snapshot (`frontend/scripts/module-catalog.json`) — without them the backend refuses
  the module at startup and the commit hook refuses the snapshot

From there your module can:
- **Register API routes** by implementing `BaseModule.register_routes()` to return the module's `APIRouter`, or declaratively with `define_module(router=router)`.
- **Subscribe to events** via `context.subscribe("item.created", handler)`
- **Emit events** via `context.emit("my_module.my_event", payload)`
- **Inject UI slots** by registering contributions with the frontend `moduleRegistry` and `slotComponent(...)`, then rendering them with `<TypedSlot>`.

**[Full Module Developer Guide →](MODULES_GUIDE.md)**

---

## 🌍 Translations

Languages come in two classes, declared in one place per side of the wire
(`frontend/src/i18n/languages.ts`, the `community` flag of an entry;
`backend/app/i18n/_types.py`, `COMMUNITY_LANGUAGES`) and held to each other by
the wire parity gate.

- **Maintained languages** (`en`, `pl`, `de`, `fr`, `es`): every change brings
  all of them, and the gates require the full set — the core coverage gate
  (which reads `common`, `items`, `labels` and `locations`),
  the parity tests next to the modules, the backend error catalog and the
  module validator (`manage.py module validate`).
- **Community languages** (`pt`, Brazilian Portuguese, is the first): they
  ship at whatever coverage they have and no change has to translate them. A
  string a community language has not got yet is read in English — per key in
  the frontend (i18next `fallbackLng`) and per key in the backend error
  catalog and in a module's server-side messages. The language menu marks
  them as community translations with the share of the interface they hold,
  declared in `frontend/scripts/translation-coverage.json`. They catch up in
  batches: a person who speaks the language edits the JSON files (the core
  catalogs under `frontend/src/i18n/locales/<lang>/`, a module's
  `frontend/src/modules/<name>/i18n/<lang>.json` and
  `backend/app/modules/<name>/i18n/<lang>.json`, and
  `backend/app/i18n/_errors_<lang>.py`) and opens a pull request, or an agent
  pass fills the gaps. After a batch, run
  `TRANSLATION_COVERAGE_WRITE=1 npx vitest run
  src/i18n/__tests__/coreLocaleParity.test.ts` to declare the new
  number. The gate holds a community language to the count of keys it
  declared, not to a share of English — English grows with every change, and
  the language is not asked to follow — so it fails only when the language
  loses translations it already held. Never write the declaration by hand.

To make a language a community one, give its entry in `languages.ts`
`community: true` and list it in `COMMUNITY_LANGUAGES` in `_types.py`; its
error catalog is a plain `dict[str, str]` that may hold fewer keys than
`ErrorMessages`, registered in `COMMUNITY_ERRORS` in `backend/app/i18n/__init__.py`
(no row in `_CATALOGS`). A language is promoted to maintained by removing both
declarations, moving its error catalog from `COMMUNITY_ERRORS` to a row in
`_CATALOGS` (a complete `ErrorMessages`) and declaring `100` in
`translation-coverage.json`, once it is complete and someone will keep it so.

The list of supported languages lives in exactly two places — one per side of
the wire — and a parity gate holds them to each other:

- **frontend/src/i18n/languages.ts** — one entry per language in `LANGUAGES`,
  carrying the code and the picker's display name. That one array is the
  `Language` type, `SUPPORTED_LANGUAGES`, `LANGUAGE_NAMES`, the picker's menu
  and what `resolveLang` may resolve to.
- **backend/app/i18n/\_types.py** — the `Language` literal. `SUPPORTED_LANGUAGES`
  is `get_args` of it, and every other backend place reads that: the user
  schema, the comma-decimal set (from CLDR through Babel), the
  campaign-email languages, the PDF Babel locales, the public storage-type
  API's allowed codes and the attestation scheduler.

`frontend/src/i18n/__tests__/languageWireParity.test.ts` reads the backend's
literal straight out of `_types.py` and compares it with the frontend array,
the way the currency and country gates do. Each code gets a test title of its
own, so a language that reaches one side only fails naming that language —
`it is shipped on both sides` goes red with `backend/app/i18n/_types.py does
not ship it`, not with a general "the lists differ".

Core translation files live in `frontend/src/i18n/locales/`, and the loader
serves a locale directory only for a language in the array. The test gates
discover the languages from the directory itself and hold it to the array in
both directions.

Both core and module catalogs are found by `import.meta.glob` and loaded on
demand: the app fetches the catalogs for the language it starts in, and pulls
another language's when the reader switches. For the *loader* and for the
test gates adding a language is just files and one array entry — the gates
read the locales directory, and a directory appears in them without any list
being edited. The steps below are what is left.

The core locale tree contains these ten namespaces for every supported language:

```
frontend/src/i18n/locales/
├── en/
├── pl/
├── de/
├── fr/
├── es/
└── pt/          (community language)
```

Each locale directory contains:

- `auth.json`
- `categories.json`
- `common.json`
- `items.json`
- `labels.json`
- `modules.json`
- `onboarding.json`
- `permissions.json`
- `scan.json`
- `locations.json`

Module-specific translation bundles live under
`frontend/src/modules/{name}/i18n/{language}.json`, and are registered only for
languages listed in `SUPPORTED_LANGUAGES`.

To add a new language (for example, Italian), walk this list top to bottom —
eight steps, three of which (2, 4 and 6) are writing translations rather than
finding places. A community language skips what it has no catalogs for yet (a partial
step 2 and 4 and a partial step 6 are allowed); step 3 declares what it has.

1. `frontend/src/i18n/languages.ts` — one entry in `LANGUAGES`: the code,
   the short name the button shows, the full name the menu shows, the flag.
   That entry is the frontend's whole list
2. `frontend/src/i18n/locales/<lang>/` — the ten namespace files (copy an
   existing language's directory and translate). The gates pick the language
   up from the directory alone
3. Declare the language's coverage in
   `frontend/scripts/translation-coverage.json` — `100` for a maintained
   language, which the gate holds to every English key whatever the file
   says; for a community language its share and the count of keys it holds.
   A community language falls back to English per key, the gate fails when it
   holds fewer keys than it declared, and the declarations are refreshed only
   by writing what is (`TRANSLATION_COVERAGE_WRITE=1 npx vitest run
   src/i18n/__tests__/coreLocaleParity.test.ts`), never by hand
4. `frontend/src/modules/*/i18n/<lang>.json` — one file per module (same
   rule: copy, translate)
5. `backend/app/i18n/_types.py` — the code in the `Language` literal. That
   entry is the backend's whole list: `SUPPORTED_LANGUAGES` and every place
   that iterates languages follow it. A community language is also listed
   in `COMMUNITY_LANGUAGES` beside it
6. A new `backend/app/i18n/_errors_<lang>.py` translating every key of the
   `ErrorMessages` type (English and Polish share `_errors_en_pl.py`; the
   other languages have a file each). For a community language the file is
   a plain `ERRORS_<LANG>: dict[str, str]` with the keys translated so far
7. `backend/app/i18n/__init__.py` — one row in `_CATALOGS` pointing at the
   new catalog file (a community language gets a row in `COMMUNITY_ERRORS`
   instead). `ERRORS` is built from `MAINTAINED_LANGUAGES` over that table,
   so a maintained language with no row fails at import naming the language
8. `frontend/src/types/api-generated.ts` — never edited by hand: after the
   backend steps, run `make generate-api-types` so the generated API types
   carry the new code

What used to be on this list and no longer needs a hand — each of these
reads the one list now instead of keeping a copy:

- the language picker (`frontend/src/components/LanguageSelector.tsx`) —
  reads `LANGUAGES`
- a second `Language` literal in `backend/app/schemas/user.py` — imports the
  one in `_types.py`; its own copy silently rejected codes the rest of the
  backend served
- `SUPPORTED_LANGUAGES` in `backend/app/i18n/service.py` — `get_args` of the
  literal
- `_COMMA_DECIMAL_LANGUAGES` in `backend/app/i18n/service.py` — read
  from CLDR through Babel, so a language arrives with its own decimal
  separator
- the language checks in `backend/app/modules/equipment/_router_campaigns.py`,
  `backend/app/core/public_api/location_types.py` and
  `backend/app/modules/equipment/_attestation_scheduler.py`, and
  `_BABEL_LOCALES` in `backend/app/services/pdf_utils.py` — each tests
  against, or builds from, `SUPPORTED_LANGUAGES` instead of a list of its own
- the test gates in `frontend/src/i18n/__tests__`,
  `frontend/src/lib/moduleRegistry/` and the modules — each held its own
  copy of the five codes, which made a new language invisible to it: green
  while measuring nothing

When the frontend gates run as `npx vitest run src/i18n` and the backend side
as `pytest tests/unit/test_i18n_service.py tests/unit/test_unit_labels_i18n.py`,
a complete walk ends green. What each half-finished walk produces instead:

- **Frontend only** (step 5 not done) — the interface switches to the new
  language, but the wire parity gate is red naming the language: `it is
  shipped on both sides` fails with `backend/app/i18n/_types.py does not
  ship it`. And until it is done, every API error answers in English: the
  backend resolves `Accept-Language` against its own list, and an unknown
  code falls back to the default language.
- **Backend only** (step 1 not done) — the same gate, the other way: `it is
  shipped on both sides` fails with `frontend/src/i18n/languages.ts does not
  ship it`. API errors answer in the new language, the interface stays
  English.
- **Step 1 skipped entirely** — the catalogs exist and the backend serves
  the language, but the menu keeps offering the old set: nothing renders a
  language `LANGUAGES` does not name.
- **Step 2 skipped** — the core parity gate fails in both directions at
  once: a directory it cannot find on the shipped list is an orphan catalog,
  and a shipped language without a directory does not exist. Nothing passes
  silently.
- **Step 3 skipped** — the coverage gate refuses to hold a language to no
  number: declare what is, even `0`, and grow it. The declared number is a
  baseline — a drop from it turns the gate red, unfinished does not.
- **Step 4 skipped** — a module without its `<lang>.json` falls back to
  English per key through i18next: its screens read as English inside an
  otherwise translated interface.
- **`_errors_<lang>.py` missing keys** (step 6 incomplete) — mypy refuses an
  incomplete `ErrorMessages`; bypassed at runtime, a key missing from the
  dictionary is served to the user as its raw key name, so translate all of
  them.
- **Step 6 or 7 skipped** — the app refuses to start: `ERRORS` is built
  from `SUPPORTED_LANGUAGES` over `_CATALOGS`, and a language the table does
  not answer raises a `KeyError` naming it at import, instead of serving raw
  keys at a reader.

> **Important:** Never hardcode user-facing strings in TypeScript/React source code. All text must go through the i18n system.

---

## 📏 Coding Standards

This section is a summary. The full conventions — the ones reviews hold a change to, and the ones
a coding agent you work with (Claude Code, Codex, Cursor and others read `AGENTS.md` on their own)
should follow — live in [`AGENTS.md`](AGENTS.md) (workflow and the pre-push gate),
[`backend/AGENTS.md`](backend/AGENTS.md), [`frontend/AGENTS.md`](frontend/AGENTS.md) and
[`frontend/UI_GUIDELINES.md`](frontend/UI_GUIDELINES.md). Where this summary and those files
disagree, those files win.

### Python (Backend)
- **Formatter/Linter**: `ruff` (run `make format` and `make lint`)
- **Quotes**: Single quotes `'` for strings
- **Type hints**: Required for all function arguments and return values
- **Pydantic v2**: Use for all API input/output schemas
- **SQLAlchemy 2.0**: Use `select()` + `scalars()`, not legacy `query()`
- **Error handling**: Raise the coded exceptions from `backend/app/core/exceptions.py` (`NotFoundException`, `ForbiddenException`, `ConflictException`, …) or use `@map_service_errors` in a service, never a raw `HTTPException` — a raw one answers a bare sentence with no error code, and the architecture lint refuses a new one. The mapping table is in [`backend/AGENTS.md`](backend/AGENTS.md)
- **No hardcoded i18n strings**: Use `get_error_message(key, lang)` for backend error messages

### TypeScript (Frontend)
- **Prefer functional components** with hooks
- **No `any` types** — define interfaces in the domain file under `frontend/src/types/` (`index.ts` only re-exports them; a type for API data aliases or mirrors `api-generated.ts`)
- **TailwindCSS** for styling — no external CSS files
- **React Query** for server state, **Zustand** for global client state
- **i18next** for all user-facing text — no hardcoded strings

### Tests
- Every new API endpoint must have at least **one integration test**
- Run with: `make test-backend`, or `docker compose exec backend uv run pytest -n 4 -q --tb=short` (see *Test workers* above)
- Place core tests in `backend/tests/integration/` or `backend/tests/unit/`, and a module's own tests in `backend/app/modules/<name>/tests/`

---

## 🚀 Submitting a Pull Request

1. **Fork** the repo and create a branch from `dev`
2. **Sign the CLA** (once, ever) — read [About the Contributor License Agreement](#-about-the-contributor-license-agreement) first: you keep your copyright, and a trivial fix a maintainer labels `cla: trivial` skips signing entirely. The CLA bot prompts on your first PR.
3. **Make your changes** following the coding standards, tests first
4. **Run the pre-push gate** — the full backend and frontend suites with their coverage floors (see [Making Changes](#making-changes)); do not open the PR red
5. **Write a clear PR description**:
   - What does this PR do?
   - Why is this change needed?
   - How was it tested?
   - Screenshots for UI changes
6. **Submit the PR** and wait for review

### PR Checklist

- [ ] **CLA signed — or a trivial fix a maintainer labelled `cla: trivial`** (bot prompts on first PR)
- [ ] Pre-push gate green: `make test-coverage`, `docker compose exec -T frontend npx tsc --noEmit`, `docker compose exec -T frontend npx vitest run --coverage`, plus `make lint` (backend changes) and `make check-frontend` (frontend changes)
- [ ] Every commit accepted by the pre-commit hook (it checks the whole tree; fix what it reports with `make format` / `make frontend-format`)
- [ ] New features have tests
- [ ] i18n strings are in JSON files, not hardcoded
- [ ] Documentation updated if needed
- [ ] No `console.log` or debug prints left in code

### What runs on your pull request

Pull requests target `dev`. Two workflows are in the tree for one: the CLA
check (`.github/workflows/cla.yml`, see above) and CI
(`.github/workflows/ci.yml`), triggered by pushes and pull requests to `dev`
and `main`. CI skips the backend or the frontend half when the change does not
touch it.

CI answers after you have pushed; the local gates are the ones that count for
your branch. The pre-commit
hook (`make setup-hooks`) runs the formatters, linters and contract checks on
every commit; before you open the pull request, run the rest yourself:

```bash
make test-coverage                                       # backend suite + coverage floors
docker compose exec -T frontend npx vitest run --coverage  # frontend tests + coverage floors
make lint                                                # backend checks the hook skips
make check-frontend                                      # type check, build, frontend gates
```

Say in the pull request description which of these you ran.

---

## 🐛 Reporting Bugs

When filing a bug report, please include:

**Environment:**
- OS: (e.g., Ubuntu 26.04)
- Docker version: `docker --version`
- Browser and its version: (Help → About in the browser)
- Inventari version: (Settings → About, or the `version` field of `/health`)

**To reproduce:**
```
1. Go to '...'
2. Click on '...'
3. See error
```

**Expected behavior:**
> What should have happened?

**Actual behavior:**
> What actually happened?

**Logs:**
```bash
docker compose logs backend --tail=50
```

---

## 💬 Getting Help

- 📖 [Read the docs](docs/README.md)
- 💬 [Start a Discussion](https://github.com/InventariLabs/Inventari/discussions)
- 🐛 [Open an Issue](https://github.com/InventariLabs/Inventari/issues)

---

**Thank you for making Inventari better!** 🏠✨
