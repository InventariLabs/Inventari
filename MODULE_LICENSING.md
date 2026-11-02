# Module Licensing — Additional Permission for Modules

**Version 1.0**

Inventari is licensed under the [GNU Affero General Public License v3.0](LICENSE).
This document is an **additional permission** granted under **Section 7 of the AGPL-3.0**
by **Jerzy Piątek** (jerzy@inventari.app), the copyright holder of Inventari. It applies in
addition to the AGPL-3.0 and does not remove any of its terms.

Its purpose is simple: **a module you build on Inventari's public extension points is
yours to license as you see fit.** Modules make the platform worth more to everyone,
and nobody builds one on a licensing question they cannot answer.

---

## 1. The grant

For any version of Inventari that includes this file, the copyright holder grants every
recipient an additional permission: **a module that interacts with Inventari only through
the public extension points listed in section 2 may be licensed, distributed and sold
under any terms its author chooses**, including proprietary and commercial ones, and
carries no obligation to be released under the AGPL-3.0.

This permission is **irrevocable for the versions in which it appears**. A later version
of Inventari may narrow or withdraw it, but that has no effect on any version already
released with this file, nor on modules built against such a version. You never need to
worry that an upgrade of the platform retroactively changes the licence of your module.

Two things follow that are worth stating plainly, because they are the questions people
actually ask:

- **You do not owe anyone your module's source code**, whether you distribute it, sell
  it, or offer it as part of a network service.
- **Modifications to Inventari itself remain under the AGPL-3.0.** Patching the core and
  shipping or hosting the result carries the usual obligation, and this permission does
  not touch it.

## 2. What the permission covers

The permission applies to a module that interacts with Inventari **exclusively** through
its public extension points. On the backend those are:

- **`CoreAPI`** (`app.core.public_api`) — the backend facade,
- **the module manifest and registry** (`manifest.json`, `module.yaml`, `define_module`,
  and the `BaseModule` hooks `on_enable`, `on_disable`, `on_install`, `on_startup`),
- **module-local database tables** with module-local migrations,
- **cross-module public APIs** (the `*_api.py` contracts),
- the documented **REST API** and the **events/webhooks** surface.

On the frontend they are the registration and extension surface: `FrontendModule`
registration, routes, `TypedSlot` contributions, `navOverrides`, `i18nOverrides`,
`columnContributors`, dashboard widgets and settings sections. A frontend module is
covered on the same terms as a backend one, and for the avoidance of doubt this includes
importing the types and components those extension points are declared with, and being
built into the same application bundle as the core.

Using these interfaces is what they exist for. Importing the Python or TypeScript modules
that define them, subclassing `BaseModule`, registering routes and hooks, and shipping
your module in the same process and the same bundle as the core are all inside the grant.

Where the list above names specific symbols, it describes the surface **as documented for
the version you build against**. The permission attaches to that version: if a later
release renames or removes an extension point, your existing module does not fall out of
the grant retroactively.

## 3. What the permission does not cover

The permission does not reach your work — and the AGPL-3.0 applies to it in full — if you:

- modify, copy, or adapt **core source code** (`backend/app/`, or `frontend/src/` outside
  your own module directory) into your module,
- bypass the public interfaces by importing core internals that are not documented as
  public (for example `app.models`, `app.services`, `app.database` from module code),
- distribute Inventari, or a modified version of it, **bundled with** your module as a
  single work.

If you need something the public interfaces do not provide, open an issue or a pull
request. Extending the public surface is always preferred over reaching around it, and it
keeps your module inside this permission.

## 4. Declaring your module's licence

A module declares its licence in its manifest (the field is optional: a module that
leaves it out is listed without one):

```yaml
# module.yaml
license: "MIT"   # any SPDX identifier, including "Proprietary"
```

The module store in Settings shows that identifier on each module's card. Proprietary modules
are welcome, and the licence you choose has no effect on what your module is technically
allowed to do.

Two things are separate from this permission and worth not confusing with it:

- **Modules accepted into the main Inventari repository** are AGPL-3.0 and require a
  signed [CLA](CLA.md), like any other contribution to the core.
- **The official catalogue may set its own terms** for listing, review and certification
  (see [ADR-019](docs/adr/ADR-019-modules-are-certified-not-sandboxed.md)). Those are
  conditions of being distributed by us, not conditions of this permission: a module that
  is never listed still has every freedom granted here.

## 5. Why this is the position

The modules in this tree run inside the core's process, on its ORM registry and its
request session, and call it as plain Python functions. Under the FSF's reading of
plugins that makes a module part of one combined program with the core, so without an
explicit permission a third-party module could not be closed. Rather than argue that such
modules are somehow separate works — an opinion that would bind nobody and could not be
relied on — the project grants the permission in writing, which can be.

The reasoning, and what it means for the core's own licence, is recorded in
[ADR-002](docs/adr/ADR-002-agpl-v3-and-dual-licensing.md).

## 6. Questions

Licensing questions: open a GitHub Discussion, or contact Jerzy Piątek at
jerzy@inventari.app.
