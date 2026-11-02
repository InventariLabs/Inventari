# ADR-019: Modules Are Certified, Not Sandboxed

## Status

Accepted — 2026-09-08

## Context

The module system was described in the vocabulary of a sandbox. The
`capabilities` manifest field read like runtime permissions; the `db_facade`
docstring spoke of "sandboxed module code" crossing a "sandbox boundary"; the
guides promised that undeclared resources would be "blocked". None of that is
what the system does.

What the system actually does: the AST safety scan matches a module's import
statements against a fixed vocabulary of names (`module_safety.CAPABILITY_MAP`
and `FORBIDDEN_IMPORT_PREFIXES`) and refuses modules whose imports leave the
declared set. It is a static, review-time lint plus a load-time architecture
gate. Module code that runs, runs in-process with the same database and
filesystem access as the Core — and the lint matches imports by literal name,
so `pathlib.Path().write_text()`, `http.client`, `aiohttp` and `db_facade`
itself all sit outside what it can see. A capability system it is not, and
calling it one tells an operator a falsehood about where their safety comes
from.

The decision this ADR records was resolved on 2026-09-07: **the module model
is certification and the operator's own responsibility, not confinement.**
What forced it is the distribution model, not a threat model. Inventari is
self-hosted: the operator themselves, knowingly, runs `module install
<git-url> --rev <tag>` on their own server. That is the semantics of
`pip install` — nobody sandboxes pip, npm or apt. Sandboxing pays for itself
where a provider runs someone else's code on behalf of a user who made no
choice (browsers, phones, edge workers). The nearest comparable products do
the same: Odoo runs Python modules in-process behind a reviewed marketplace;
WordPress runs sixty thousand plugins in-process behind a reviewed directory;
Grafana signs packages and leaves an explicit switch for unsigned ones.

The alternative road — isolating modules out of process — was measured and is
closed, not merely deferred. 236 of 282 public `core_api` methods (84%) take a
database session as an argument, and the transactional contract passes that
session inside a request's transaction. A module behind a process boundary
cannot share it, so out-of-process modules would need a second API surface, a
second error model, and a compensating-transaction scheme for writes that
today simply commit together. That cost buys isolation for a threat the
distribution model does not have: the operator installs what they choose.

## Decision

**A module's safety story is who certified it, not what we claim to contain.**
The documentation says so, and three trust levels are named wherever module
trust is discussed:

1. **Core** — the modules shipped in the repository (`backend/app/modules/`),
   reviewed like the rest of the codebase and released with it.
2. **Certified** — external modules reviewed and signed for the catalog; the
   machinery for this exists (`module sign` / signature verification in the
   installer, `MODULE_SIGNING_PUBLIC_KEYS`, identity fields in the tracking
   record), with catalog review itself still a process to run.
3. **Foreign** — anything installed from another source. It runs with the
   full power of the server process, on the operator's own responsibility;
   pinning a revision and reading the diff is the recommended hygiene, not a
   protection the platform extends.

The AST scan keeps its role and keeps its honest name: an import-name lint
that enforces the architecture contract
([ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md)) and gives a certifying
reviewer a cheap, repeatable first pass. It does not guard resources, and the
docs no longer say it does.

### Alternatives considered

| Option                                                           | Why rejected                                                                                                                                                                                                 |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Keep the sandbox vocabulary, build a real sandbox to match it    | Out-of-process modules are excluded by the transactional contract — 84% of `core_api` methods take the request's session, and the cost analysis is written down here so the topic is not reopened by default |
| In-process capability enforcement (intercept `open`, sockets, …) | A second security boundary maintained across every code path, defending a choice the operator already made knowingly; Odoo, WordPress and Grafana all declined the same trade                                |
| Say nothing, delete the word "sandbox" quietly                   | Leaves the trust decision undocumented; the next contributor reading `capabilities` reinvents the same falsehood                                                                                             |

## Consequences

**Positive**

- The docs, the manifest schema and the installer's note all describe one
  system: certification up front, the operator's judgement at install, a lint
  in review and at load.
- The three trust levels give the certification work a vocabulary to attach
  to — signatures, the identity fields of the tracking record and the
  manifest's `module_type` field are
  the remaining machinery, now named as such.
- No false reassurance: an operator who reads the docs learns that review and
  pinning are the safety mechanism, not containment.

**Negative**

- The platform offers no runtime containment for installed module code:
  modules execute in the server process with full privileges. Operators
  should install only modules they trust; certification is the vetting
  mechanism, complemented by signatures (`module sign`, verified at install) and the operator's own
  review discipline.
- Documentation and code must keep agreeing about what the scan is; a future
  change that makes the scan smarter must not be described in the old
  vocabulary again. This ADR is the reference both are held to.

## References

- [ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md) — the CoreAPI facade
  and the AST architecture lint whose description this ADR corrects.
- `backend/app/cli/commands_module.py` — the installer's note, which already
  stated the truth in the CLI before the docs caught up.
- Prior art: Odoo's app store review, WordPress.org plugin review, Grafana's
  plugin signing.
