# ADR-002: AGPL v3 License + Dual Licensing

## Status

Accepted — 2026-06-22

## Context

Inventari targets two audiences simultaneously: home/individual users (fridge
tracking, recipes) and businesses (SMB warehouse, HoReCa, IT asset management).
Every fork-considerer and contributor will ask: **why not MIT/Apache?** The
license choice defines what users and contributors may do with the code, what
obligations a hosted deployment carries, and the long-term sustainability of
the project.

Key constraints:

1. **Self-hosted is the primary deployment.** Users run Inventari on their own
   infrastructure (Docker, homelab). Permissive licenses (MIT) would allow
   anyone to fork, rebrand, and offer a hosted version without contributing
   back.
2. **Contributions must be relicensable.** To offer the codebase under
   commercial licenses as well, without AGPL obligations attaching to that
   offering, the maintainer must hold licensing rights to all contributions.

## Decision

**GNU AGPL v3 for the open-source edition + Individual CLA for contributions.**

- **AGPL v3** ("GNU Affero General Public License v3") governs the
  open-source release. The network-use clause (§13) requires anyone who
  offers Inventari as a network service to share their modifications under
  the same license.
- **CLA v1.0** (individual, effective February 2026) grants Jerzy Piątek
  (jerzy@inventari.app) a perpetual, worldwide, non-exclusive, royalty-free,
  irrevocable copyright license to sublicense contributions under any license,
  including proprietary/commercial licenses. Contributors retain their copyright.

**The licensor is Jerzy Piątek personally, not the organization.** InventariLabs
is the GitHub organization the Project is maintained under; it is not a separate
legal person and is not a party to this ADR. Should the Project later move to a
company, [CLA.md](../../CLA.md) §8 lets the Maintainer assign the Agreement and
the rights granted under it to the successor, so such a move needs no fresh
consent from contributors.

This combination enables **dual licensing**: the community edition is AGPL
(free, copyleft), while enterprises who cannot comply with AGPL (e.g., cannot
open-source their modifications, or want it embedded in a proprietary stack)
can purchase a commercial license.

### Alternatives considered

| License                                     | Adoption                                     | Copyleft strength                                                                   | Verdict                                                                                                          |
| ------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **MIT / Apache 2.0**                        | Highest — no friction                        | **None** — forks can be hosted and redistributed without giving back                | Rejected. No requirement to share modifications.                                                                 |
| **BSL / BUSL** (HashiCorp, Sentry 2019–2023) | Medium — "eventually open source"            | Strong while in force — source-available, converts to an open license after N years | Rejected. Not OSI-approved, discourages community contributions, complex license-change governance.              |
| **GPL v3** (no network clause)              | High                                         | Weak for network use — SaaS deployments exempt from copyleft                        | Rejected. A hosted deployment could use GPL code without sharing modifications. AGPL's §13 closes this loophole. |
| **AGPL v3** (chosen)                        | Medium-high — common in self-hosted projects | **Strong** — network copyleft requires sharing modifications offered over a network | **Chosen.** Matches the self-hosted deployment model.                                                            |
| **Dual AGPL + commercial** (iText, MongoDB until 2018) | Same as AGPL for community                   | Strong — plus a commercial license path for users who cannot comply with AGPL       | The model AGPL + CLA enables.                                                                                    |

### Why AGPL over BSL

- **OSI-approved.** AGPL is a recognized open-source license; BSL is
  "source-available" but not OSI-approved, which discourages contributions
  and some package registries.
- **Community trust.** AGPL is widely used across the self-hosted ecosystem.
  The audience understands and accepts it.
- **Simplicity.** One license for the community edition. BSL requires
  defining "non-production" use, change dates, and additional use grants —
  legal complexity for both maintainer and user.

### Why an Individual CLA (not Corporate)

The current CLA is individual-only (Version 1.0, February 2026). This is
intentional for the current stage:

- Contributors are individuals (hobbyists, indie devs), not corporations.
- Individual CLAs are simpler to sign and review.
- A corporate CLA can be added when enterprise contributors arrive, without
  changing the individual CLA.

### How the CLA is explained to contributors

`CONTRIBUTING.md` explains the CLA before the pull-request procedure
asks anyone to sign it, and the order of that explanation is deliberate:

- **Copyright retention is the opening sentence.** The most common reason a
  contributor backs away from a CLA is the belief that signing hands over
  ownership of their work. That belief is wrong here — the project receives a
  license, not a deed — and correcting it after the request has already been
  made corrects it too late.
- **The commercial sale is named, not implied.** A CLA whose purpose goes
  unstated reads as boilerplate covering something. Naming dual licensing as
  the reason costs nothing, because it is public in this ADR anyway, and a
  contributor who objects to it is better off knowing before writing the patch
  than after.
- **The copyleft commitment answers a specific fear, in writing.** Contributors
  have watched projects relicense away from open source after accumulating
  outside contributions, and a CLA is the instrument that makes that possible.
  Pointing at the AGPL file does not answer that fear, because a license file
  describes today and the fear is about tomorrow. So the explanation states the
  commitment in prose: the community edition stays under an OSI-approved
  copyleft license.
- **The trivial path is offered in the same breath, not in a footnote.** Most
  first contributions are typo fixes. Making someone read and sign an agreement
  to correct a broken link is friction that buys the project nothing, so the
  trivial-contribution waiver is stated where the obligation is stated.

What this framing deliberately does **not** do is claim that the license
_cannot_ change. That would be a legal claim the project is not in a position
to make — the copyright holder could relicense — so the text gives a public
commitment instead, which is the honest form of the same assurance.

## Consequences

### Positive

- **Copyleft protection.** AGPL's network clause requires anyone offering
  Inventari as a network service to share their modifications under the same
  license. Users who cannot comply with AGPL can obtain a commercial license.
- **Contribution safety.** CLA ensures Jerzy Piątek can relicense the
  codebase commercially without tracking down every contributor.
- **Community alignment.** AGPL is well-understood in the self-hosted
  ecosystem; contributors know the deal.
- **Module licensing compatibility.** Community modules can be any license;
  first-party modules can also be proprietary because the project owns their
  copyright, and third-party ones because of the additional
  permission granted in [MODULE_LICENSING.md](../../MODULE_LICENSING.md).
  What that permission rests on is set out in "Modules and the
  derivative-work question" below.

### Negative

- **Adoption friction.** Some organizations have "no AGPL" policies (notably
  cloud providers). This is a known trade-off of copyleft, accepted
  deliberately.
- **CLA overhead.** Every non-trivial contributor must sign. Automated via the `cla.yml`
  GitHub workflow (blocks PR merge until signed).
- **No corporate CLA yet.** Contributions made on behalf of an employer
  need a corporate CLA, which has yet to be drafted and reviewed by a lawyer;
  until it exists, only individuals can sign.

### Risks

- **"Relicense on MIT" pressure.** Contributors will periodically propose
  switching to MIT "for more adoption." This ADR documents why that won't
  happen: MIT would remove the network copyleft the project relies on, and
  with it the distinction that makes dual licensing possible.
- **Mixed-ownership files.** If a contribution lands without a signed CLA,
  that file cannot be relicensed commercially. Mitigation: `cla.yml` blocks
  PR merge until CLA is signed.
- **AGPL misinterpretation.** Some users believe AGPL "infects" their entire
  stack. It reaches derivative works of Inventari; unrelated software that
  merely talks to a deployed Inventari over its HTTP API is not reached. The
  modules shipped in this tree are the harder case — they share process, ORM
  registry, session and schema with the core — and the project answers it by
  granting an explicit additional permission, not by asserting that such
  modules are separate works. See "Modules and the derivative-work question".

## Modules and the derivative-work question

An earlier revision of this ADR stated that modules "interact via the
CoreAPI/EventBus (which are separate works)". That claim was never argued
anywhere in the tree, and the technical facts do not support it as a
self-evident reading:

- **One process.** Module routers are registered into the same ASGI
  application at startup — `backend/app/main.py` folds each module's router
  into `api_v1_router`, so a request a module serves runs in the same
  interpreter, with no socket or pipe at the boundary.
- **One ORM registry.** Module models inherit the core's declarative `Base` —
  some through the `app.core.db_facade` facade, most straight from
  `app.database`, which is where the facade re-exports it from anyway. Module
  tables and core tables therefore live in one metadata and one schema
  (the one exception, the first-party `nutrition` module, keeps its product
  catalogue in a separate database on a base of its own).
- **One session.** A module endpoint receives its `AsyncSession` from the
  core's own request dependency (`app.core.deps.get_async_db`) — the same
  session object the core's endpoints run on, inside the same transaction.
- **In-process calls, not IPC.** Module code imports the `core_api` facade
  and calls it as plain Python functions, and shares DTO types from
  `app.core.contracts`.
- **Schema joins across the boundary.** Module tables carry foreign keys into
  core tables.

Under the FSF's reading of plugins — separate programs communicate as
separate processes over sockets or pipes, while components that share memory
space, call each other's functions and exchange internal data structures form
one combined program — a module in this tree sits on the "one program" side.
Absent anything further, a third-party module would be a derivative work of
the core and could not be distributed under a closed license.

**That is why the permission is explicit rather than interpretive.**
[MODULE_LICENSING.md](../../MODULE_LICENSING.md) grants an additional
permission under Section 7 of the AGPL-3.0: a module that stays inside the
documented extension points may carry whatever license its author chooses,
including a proprietary one. A written grant from the copyright holder holds
regardless of how the derivative-work question would be decided; an opinion
in an ADR would not. The two documents divide accordingly — this ADR explains
why the grant is needed, MODULE_LICENSING.md _is_ the grant.

The grant is bounded by the same line the analysis above draws: it covers the
documented interfaces, and it does not cover a module that reaches into core
internals, patches core source, or ships the core bundled with itself. Those
remain derivative works under AGPL-3.0.

First-party modules distributed under a proprietary license need none of this.
The project owns their copyright and can license its own work as it sees fit.

Granting the permission is also the position the project wants on its
merits, not a concession. A module raises what the platform is worth and is
worth nothing without it, so a third-party module — closed or open — is
someone else's investment in Inventari. What the project keeps hold of does
not run through the module's licence anyway: the core stays AGPL, the CLA
keeps it relicensable, the public surface is ours to shape, and the
catalogue decides what we distribute and certify (see
[ADR-019](ADR-019-modules-are-certified-not-sandboxed.md)). Those are the
levers. Requiring modules to be AGPL would not add to them, and would fall
first on the people least worth deterring: a customer adding an integration
to their own deployment, and an author who would otherwise have shipped
something.

## Implementation

- **LICENSE** — AGPL v3 full text (present); the project's copyright line
  (Copyright 2026 Jerzy Piątek) is in **NOTICE**.
- **CLA.md** — Individual CLA v1.0 (present, effective February 2026).
- **`.github/workflows/cla.yml`** — Blocks PR merge until CLA is signed.
- **`.github/workflows/license-scan.yml`** — Checks dependency licences
  against `THIRD_PARTY_LICENSES.md`.

## References

- LICENSE file (AGPL v3)
- CLA.md (Individual CLA v1.0)
- Precedents: iText (AGPL + commercial), MongoDB until 2018 (AGPL + commercial)
- MODULE_LICENSING.md — the additional permission for modules, granted under
  AGPL-3.0 §7 (Version 1.0)
- FSF, "GPL-Incompatible Plugins" and "Mere Aggregation" entries in the GPL
  FAQ — the plugin/combined-work reading this ADR applies to its own modules
