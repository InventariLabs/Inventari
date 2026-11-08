# AI Agent Instructions (AGENTS.md)

This file holds **cross-cutting** rules (workflow, branching, quality gates). Scope-specific conventions
live next to the code they govern — read them before editing that tree. Code comments cite them as
`AGENTS.md §<number>`:

- **[`backend/AGENTS.md`](backend/AGENTS.md)** — §3 Modular Architecture & DB Access (Golden Path / Escape
  Hatch), §4 Core Neutrality, §5 Safety, Backend Engineering Standards §1–8, Sync/Async Rule, Stock
  Posting Rules (ADR-022), Cross-Module API Contracts, backend anti-patterns.
- **[`frontend/AGENTS.md`](frontend/AGENTS.md)** — Frontend Engineering Standards §1–7, i18n rules,
  frontend anti-patterns.
- Subsystem details: `docs/subsystems/` — read the matching file before touching a subsystem.

**Inventari** is a modular, vertical-agnostic inventory management platform (FastAPI + React). The Core is
domain-neutral; all vertical-specific logic lives in modules.

## Task & Plan Management

Task and plan tracking is internal to the maintainers and is **not** part of
this repository. External contributors don't need it — open a GitHub issue
first and reference it from the pull request. Internal task IDs and private
plan references appear nowhere in this repository — not in code, comments,
docs, test names or file names, and not in its history. `make lint` scans the
whole public tree for them (`backend/scripts/check_internal_ids.py`).

### Commit messages

The history is published with the code, so a commit message is read like a
comment: it says *what* changed and *why*, in prose. For an outside reader it
is the only record of the change there is.

- A subject of about 72 characters (a conventional prefix such as
  `fix(scope):` is fine), then a blank line and a body wrapped at about 72 for
  every change the subject alone does not explain: the problem as a user met
  it, its cause, why this fix and not another, and what follows from it. The
  diff shows what changed; the body says why.
- A merge commit has a short subject and a paragraph describing the branch as
  a whole, the way a pull request description does.
- No task or plan identifier, no branch name, and nothing about who or what
  made the change — the maintainers' private development tooling stays out.
  The task lives with the maintainers, the branch in git.
- A merge takes its subject with `-m "<what the merge brings>"`. When a branch
  catches up with `dev` and git writes its own subject ("Merge remote-tracking
  branch 'origin/dev' into …"), the hook replaces it with "Merge the
  development line"; any other default merge subject is refused.
- An issue reference is welcome: "Fixes #12" in a merge message closes the
  issue when the change lands on `dev`. Commit hashes are public too.
- The `commit-msg` hook (`.pre-commit-config.yaml`, installed by
  `make setup-hooks`) refuses a message that breaks this. `make
  check-commit-messages` reads the messages of the commits a push would publish
  (`RANGE=origin/dev..HEAD` by default), for commits made where the hook did
  not run. It fails only on a task or plan identifier or a private word, which
  must not become public; a branch name or git's own merge subject it reports
  and lets through, because rewording a commit already pushed rewrites
  published history. Wording is fixed when it is free: at the commit.

### Changelog

The history in [`CHANGELOG.md`](CHANGELOG.md) starts at `v0.11.0`, the first
public release. Until it is cut, its `v0.11.0 - unreleased` section is a
description of what that release does — an opening paragraph, then what a
reader finds in it, grouped by area — not a list of changes: nobody
outside the maintainers runs an earlier version, so a fix, a rename, a removal
or a contract change before the release has no reader to warn. A branch
touches the section only when it adds something a reader of that note should
know about, or makes one of its sentences untrue — then it adds or corrects
that sentence, without *Fixed*, *Changed* or *Removed* entries and without
**Breaking**.

From the first change after `v0.11.0` on, a change that a user, an instance
administrator or a module author will notice gets an entry in `CHANGELOG.md`
under `## Unreleased`, in the same branch that makes the change. The author
writes it and the reviewer checks it.

- Group it under *Added*, *Changed*, *Fixed* or *Removed*, in prose that says
  what the reader will see differently, not which files moved.
- A breaking contract change (a module-facing API, a manifest field, a
  configuration variable, a stored format) is marked **Breaking** and says
  what the affected party must do.
- Refactors, tests, baselines and CI changes get no entry.
- When a release is cut, `## Unreleased` becomes `## v<version> - <date>` and
  `backend/pyproject.toml`, `frontend/package.json`, `backend/uv.lock`,
  `frontend/package-lock.json`, `docs/api/openapi.json` and the README's
  release section carry the same number. `make release-db-snapshot`, run on
  the release commit before the tag, adds the release's database to the upgrade test (CONTRIBUTING.md,
  *Upgrading from a released database*).

## Development Rules

0.  **NO DESTRUCTIVE ACTIONS WITHOUT BACKUP**: Never run `git reset --hard`, `git clean -fd`, or delete uncommitted files without explicit user confirmation and suggesting a `git stash` or `backup branch` first.
2. **Branches**: Every feature or fix must be developed on a separate branch — never commit directly to `main`.
   - Naming: `feature/<short-description>`, `fix/<short-description>`, `chore/<short-description>` — a description, never a task identifier.
   - **Always branch from `dev` (not `main`)** — `dev` is the integration branch for in-progress work.

   Backend-only rules **3 (Modular Architecture & DB Access)**, **4 (Core Neutrality)** and **5 (Safety)**
   live in [`backend/AGENTS.md`](backend/AGENTS.md) under the same numbers, so existing code comments
   citing `AGENTS.md §3` / `§4` / `§5` keep resolving.
6. **Testing & Quality Gates**:
   - **Backend**: `make test` or `docker compose exec backend uv run pytest -n <workers> -q` — a fixed count, never `-n auto` (the containers have no CPU limit, so `auto` takes every core of the host). The number comes from `scripts/test-workers.py pytest`, which reads the machine's cores and free memory (and a container's cgroup limits); the `make` targets (`PYTEST_WORKERS`), CI and the Playwright config all ask it — call pytest directly with the number it prints. No suite carries a worker count fixed for one machine. Narrow the *selection* (`<file>`, `-k <expr>`) to run less. Not `--lf`: pytest's cache accumulates failures across every run in the tree; take the names from that run's summary instead.
   - **Frontend unit**: `npm run test:run` / `npx vitest run <specs>`.
   - **Frontend E2E**: `npx playwright test` (config in `frontend/playwright.config.ts`, specs in `frontend/tests/e2e/`) **pollutes whatever DB it runs against — use the isolated stack**: `make test-e2e-isolated` (dev2, ports +100, auto-provisioned). Never run E2E against the primary dev stack unless you plan to reset it afterwards.
   - **Load tests**: k6 via `docker-compose.loadtest.yml` (see `load_tests/README.md`).
   - **Pre-commit**: the installed hook runs `.pre-commit-config.yaml`, **not** `make lint` / `make check-frontend`. Each of its hooks fires when the commit stages a file it watches (Python, frontend sources, or the paths `.pre-commit-config.yaml` names) and then checks the whole tree: `ruff format --check`, `ruff check`, architecture lint, the mypy baseline (which `make lint` runs too, so a commit made past the hook is still measured), prettier and eslint (which `make check-frontend` runs too, for the same reason), the frontend module boundaries, the accessibility baseline, the two module snapshot contracts, and licence-report freshness — do not re-run those by hand in front of it. Its `commit-msg` half checks the message (see *Commit messages*). Everything else in `make lint` / `make check-frontend` the hook does **not** cover — among it the backend dead-code gate, declared imports, module purpose cards, the docs-path check, leaked internal identifiers, `uv audit`, `tsc`, the production build, the i18n, vocabulary and UI-convention gates, the frontend reachability and registry checks, the OpenAPI and API-type drift checks, and the phone budget.
   - **Dead-code gates**: vulture (backend, via `make lint`); knip, `check:i18n:unused`, `check:routes`, `check:reachable`, `check:focus-reachability` (frontend, via `make check-frontend`) — all run in baseline mode and fail only on NEW findings. `check:consumers` and `check:suppressions` (also in `make check-frontend`) keep no baseline: their registers below are the record, and an entry missing or expired there fails at once. Refresh baselines only via `--write-baseline` (never grandfather by hand). A merge conflict in a baseline file is resolved the same way: take either side, run its `--write-baseline` on the merged tree, and check that the diff against both parents carries only what the two branches changed — `frontend/scripts/function-baseline.json` has no timestamp, so two branches that freeze different functions merge without a conflict at all. `make scan-dead` runs them in non-blocking full mode and finishes with a jscpd duplication report (`make scan-duplication` on its own; 3% is the informational threshold, and duplication is born in the seams between sibling features, so read the clusters rather than the number). Consumer-route and suppression exceptions go in `frontend/scripts/integration-only.json` / `frontend/scripts/suppressions.json` — each with a reason, an owner and an expiry.
   - **CI runs after the push, the local gates before it.** `ci.yml` triggers on pushes and pull requests to `dev` and `main`, and on `workflow_dispatch`; the weekly dead-code and licence crons are off. **The local gates are the authoritative gates for `dev`** — CI only reports on a commit that has already landed. Put new checks in `make lint` / `make check-frontend` first, and in CI only as a copy of a local step; a CI step with no local equivalent is a gate no branch meets before it leaves.
   - **API contract gate** (`make check-api-types`, also run near the end of `make check-frontend`, just before `perf-phone`, which needs a built `frontend/dist/` and a running stack): `frontend/src/types/api-generated.ts` and `api-routes.ts` are generated — never hand-edit them; run `make generate-api-types` after changing any endpoint or response model. `docs/api/openapi.json` is the same kind of artifact for the outside world (Postman/Insomnia import; production serves no `/openapi.json`): `make generate-openapi` refreshes it, and `make check-openapi-fresh` (one step earlier in `make check-frontend`) fails when it drifts.
7. **Code & Documentation Language**: Code, comments, docstrings, and documentation files — **English only**.
8. **Frontend UI**: conventions live in [`frontend/AGENTS.md`](frontend/AGENTS.md). **MANDATORY** before creating or modifying a UI component: §0 of [`frontend/UI_GUIDELINES.md`](frontend/UI_GUIDELINES.md), and the sections it names for what you touch.

---

## Engineering Practice

- **Test-Driven Development (TDD):** Tests are the specification. Write the failing test FIRST, implement the minimal code to pass, refactor only once green. The red–green loop runs **the test you are writing** — one file or a `-k <expr>`, seconds each — never the suite (see *The Mandatory Gate*).
- **Commits are rollback points, not measurements**, so a commit has no test gate of its own (see *The Mandatory Gate*).
- **The smallest change that does the job.** Read the flow the change touches end to end first;
  then reuse what the codebase already has before writing something new, fix a defect in the
  shared function every caller goes through rather than at the one call site a report names, and
  add no abstraction, option or file that has no second caller. This never overrides the rules
  that keep data correct and the product usable: organization scoping, transaction ownership and
  the stock posting rules (`backend/AGENTS.md`), TDD and a test that fails without the fix,
  the five maintained languages, accessibility, and the coverage floors.

### The Mandatory Gate (the pre-push gate — once per branch, before it leaves)

The full backend suite takes minutes, almost all of it fixture setup rather than assertions; one
file takes seconds. So the gate belongs to the **branch, not the commit**: paying the full price at
each commit measures the same unchanged code over and over.

The rule is about **what** runs, not when:

- **While you write — the tests of what you are changing.** The test you are writing (TDD red,
  then green), and the test file that covers the code you just edited, when there is one. A file
  or a `-k <expr>`: seconds. This is where most mistakes are stopped.
- **At commit — nothing extra.** The pre-commit hook lints the whole tree; that is the commit's gate.
- **Before the push — the full suite, once.** It exists for the regressions that live between
  modules, which no scoped run can see.

**The pre-push gate — BEFORE `git push`:**
```bash
make test-coverage
docker compose exec -T frontend npx tsc --noEmit
docker compose exec -T frontend npx vitest run --coverage
make check-frontend   # when the branch touches frontend/
make lint             # when the branch touches backend/
```

The last two are the checks the pre-commit hook does not run (the list is in rule 6, "Pre-commit");
a branch that skips them is green for its author and red on the merge. Where a wrapper runs the
suites for you (a shared machine with a test queue), use the wrapper; the commands above are what
it runs.

Both test halves carry the coverage floors, which is why they are not the shorter commands they
look like they should be. `make test-coverage` is the suite (at `-n $(PYTEST_WORKERS)`) with `--cov-fail-under=70`
and then the **changed-line** gate (≥ 80%, `make check-diff-coverage`); `--coverage` on the frontend
side is what makes the thresholds in `frontend/vite.config.ts` apply at all. Scoped runs while you
write stay without the flag: the frontend thresholds are global, so a scoped run under `--coverage`
fails them by construction. The floors belong to the full run.

**The frontend coverage floors are a ratchet, not a dial.** The four numbers in
`frontend/vite.config.ts` are rounded down from what the full suite measures on that commit, and
the measurement they came from is recorded in the comment above them. Lowering one takes a commit
of its own that replaces that measurement and says in its message what coverage was lost and why;
a floor that can be eased in the same commit as the code that lost the coverage is not a floor.

If it fails, re-run **only the files that failed** — their names are in the summary of the run that
just failed — fix, and repeat until they pass. Then one full run, then push. A failure in a test
your branch does not touch is not a reason to run everything again: run that one test on its own;
if it fails the same way on `dev`, or its assertion depends on an order nothing guarantees, it is a
defect of its own — report it in the branch rather than re-running the suite until it passes.

- **Do not run ruff or prettier by hand.** The pre-commit hook runs them whole-tree on every commit
  that stages Python or frontend sources (only `--no-verify` skips it, and then `make lint` /
  `make check-frontend` are yours). `tsc` is yours because the hook does **not** cover it.

**Do NOT push if the pre-push gate fails.** A green subset never licenses a push — a scoped run
cannot see cross-module regressions. CI on `dev` reports only after the push has landed, so a
branch pushed with an unmeasured pre-push gate reaches `dev` with no gate in front of it.

**Green gates are not evidence on their own.** They say the code is correct; they do not say the
change does what it promised. Three things belong to the author, before the work leaves the branch:

- **Open the screen your change touches** — the console and the network tab included. The
  expensive defects here are rarely bad code. They are correct, typed, linted, green code behind
  a broken screen: a duplicate React key on a list that had just stopped being
  unique, a warning that fired while the user typed a *correct* value, 24 requests where the
  previous build sent none. Each was a minute of looking.
- **Know what your new test fails on.** Revert the source, keep the test, run it, and write down
  what broke. A test that passes both ways documents the old behaviour — worth having, but say
  which is which. An unmarked one is worse than none: it reads as proof and is not.
- **Add no new suppression in the change a gate was meant to inspect** — `eslint-disable`,
  `@ts-ignore`, `noqa`, a vulture whitelist entry, a refreshed baseline, a new allowlist prefix.
  A suppression written in the same commit as the code it hides makes "gates green" mean nothing
  for the rest of the diff. Measure it (expect `0`):

  ```bash
  git diff origin/dev...HEAD -U0 | grep '^+' |
    grep -vE '^\+\+\+ ' |
    grep -cE 'eslint-disable|ts-(ignore|expect-error|nocheck)|noqa|vulture'
  ```

  A suppression that is genuinely right — a dynamic i18n key whose consumption really is dynamic —
  is fine, but the change must say so and show the gate still has teeth without it.
