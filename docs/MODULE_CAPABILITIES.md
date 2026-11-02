# Module Capabilities

Capabilities are declared in `manifest.json` and read by the AST safety scan: a module's import statements are matched against the vocabulary behind the declared capabilities, and a module that imports outside it is refused. The scan is an architecture lint and a reviewer's first pass — **it is not a security sandbox**, and it does not guard resources at runtime (see [ADR-019](adr/ADR-019-modules-are-certified-not-sandboxed.md)).

## Trust Model

Module trust is certification and the operator's own responsibility, not confinement ([ADR-019](adr/ADR-019-modules-are-certified-not-sandboxed.md)). Three levels:

1. **Core** — shipped in the repository (`backend/app/modules/`), reviewed and released with the codebase.
2. **Certified** — external modules reviewed and signed for the catalog. Signing and verification are built (`module sign`, the installer's signature check, `MODULE_SIGNING_PUBLIC_KEYS`); certification review, an Inventari signing key and a catalogue do not exist yet, so an external module is foreign — trusted only through its author's key listed in `MODULE_SIGNING_PUBLIC_KEYS`.
3. **Foreign** — installed from any other source. Module code runs in-process with the same database and filesystem access as the Core, so a foreign module can do anything the server process can. Pin the revision, read the diff, install only sources you would trust with your database.

## Available Capabilities

| Capability | Allows | Typical use |
|---|---|---|
| `network` | `requests`, `httpx`, `urllib` | External API calls, webhooks, LLM integration |
| `filesystem` | `os`, `shutil`, `open()` | File I/O, CSV export, temp files, image storage |
| `process` | `sys` | Interacting with the Python runtime (`subprocess` stays forbidden — see the note below) |
| `database` | `sqlalchemy`, `sqlmodel` | Direct DB access (prefer CoreAPI for most cases) |

> **What the scan does not claim:** it refuses a banned object (the raw event
> bus and its `EventBus` class) reached by import, attribute, literal `getattr`, or by an app module
> handed over as a value (`vars(m)`, `m.__dict__`, `globals()`) — that counts as
> reading every name the module holds, so even `hasattr(m, x)` or `print(m)` on
> such a module is refused. Reflection through non-module objects (a function's
> `__globals__`, `inspect.getmodule`, `gc`, `sys.modules`) is beyond a static
> scan and is not covered; there is no runtime guard (ADR-019), so certification
> is the protection. The nine shipped trusted modules are not checked for banned objects.

> **Note:** `socket` and `subprocess` are listed in `FORBIDDEN_IMPORT_PREFIXES`
> (`app/core/module_safety.py`) and rejected outright by the AST validator
> **before** the capability check, regardless of which capabilities the module
> declares. The only way past such a ban is a core-granted entry in
> `CORE_EXEMPTIONS` (which `printing` holds for `subprocess`) — never a
> manifest capability. No part of `core_api` runs an external process; the only
> `subprocess` imports in `backend/app` are in CLI tooling.

## Import → Capability Mapping

| Import/Call | Required capability |
|---|---|
| `import requests` | `network` |
| `import httpx` | `network` |
| `import urllib` | `network` |
| `import os` | `filesystem` |
| `import shutil` | `filesystem` |
| `open(...)` call | `filesystem` |
| `import sys` | `process` |
| `import sqlalchemy` | `database` |
| `import sqlmodel` | `database` |

## Forbidden Imports and Calls (always rejected, no capability override)

> **Exception:** the nine shipped modules in `TRUSTED_SHIPPED_MODULES` (the
> `TRUSTED_CORE_MODULES` names that have a directory under `app/modules/`)
> are exempt from the `app.*` bans below — the third-party bans (`subprocess`,
> `socket`, …) still apply to them. Community modules get no such lift.
> Separately, the modules this repository ships are exempt from the declared
> import surface (*The Declared Import Surface* below) by their shipped name
> (`REPO_SHIPPED_MODULES`), and the architecture lint holds what each one reaches
> to the frozen list in `module_import_surface_baseline.txt`; a module installed from outside is
> not.

These are rejected by the AST validator before capability is checked
(`FORBIDDEN_IMPORT_PREFIXES` in `app/core/module_safety.py`):

| Pattern | Why forbidden |
|---|---|
| `app.models` | Bypass the CoreAPI contract |
| `app.database` | Bypass the CoreAPI contract — a module's own tables inherit `ModuleModelBase` from `app.core.contracts` instead |
| `app.core.events.event_bus` | Reserved for Core-internal use |
| `app.core._event_bus` | The bus the events facade re-exports; naming it directly is the same bypass |
| `subprocess` | Process spawning |
| `socket` | Raw network access — use `network` capability via `requests`/`httpx`/`urllib` |
| `urllib.request` | URL opening outside the `network`-capable HTTP clients |
| `builtins.eval` / `builtins.exec` | Arbitrary code execution |
| `eval()` / `exec()` / `__import__()` / `import_module()` calls | Arbitrary code execution, and dynamic import by name |

`import importlib` and `compile()` are **not** forbidden; the `import_module` function is
(see the row above). Modules are free to use the rest within the boundaries of their
declared capabilities.

## The Declared Import Surface

An installed module may import `app.` names from three paths and nothing else
(its own package aside, and the one door described below). They are `MODULE_IMPORT_SURFACE` in
`app/core/module_safety.py`:

| Path | What it carries |
|---|---|
| `app.core.module_sdk` | `define_module`, `BaseModule`, `ModuleContext`, interceptors, contributions, exceptions, dependencies, `require_module`, `get_logger`, `get_module_error_message`, `ModuleModelBase`, `SystemEvent`, pagination, and the rest of its `__all__` (migration helpers, file-reference helpers, scan providers, settings journaling; `CoreModelBase` is for the shipped modules only) |
| `app.core.contracts` | the DTOs a module exchanges with Core, and the module model base |
| `app.core.public_api` | the `core_api` facade for Core reads and writes; a few shipped modules still reach Core models directly (see the note below) |

> **Door:** a module may also import `app.modules.<m>.<m>_api` of a module this repository
> ships, when its manifest lists `<m>` under `requires`. Nothing else under another module's
> tree is open to it.

Everything else under `app.` — `app.core.deps`, `app.core.logging`,
`app.core.exceptions`, `app.i18n.service`, `app.schemas.*`, another module's
tree — is Core's own business and is refused at load with a finding that names
the SDK. It was a denylist before this list existed, so every helper a shipped
module happened to use loaded for an outsider and each became a contract nobody
had promised to keep.

The modules this repository ships predate the door. Their current reaches are
frozen in `backend/app/core/module_import_surface_baseline.txt` (one reason per
module, owner and expiry on every block) and the architecture lint keeps the
list from growing; new code in those modules imports from the SDK too.

> **Note:** a small number of trusted in-repo modules are exempt from specific
> entries above via `CORE_EXEMPTIONS` (`app/core/module_safety.py`). The
> current entries: `printing` (`subprocess`, `os`), `vision` (`httpx`), `nutrition`
> (`os`, `sys`) and `webhooks` (`socket`). Only `nutrition` imports what its entry names;
> no module in the tree imports the names listed for `printing`, `vision` or `webhooks`.
> `equipment`, `approvals` and `maker` each read Core models directly
> through a declared escape hatch (`app.models.item`, `app.models.user`,
> and `app.models.stock_quants_from_records` (the records' view, see
> [ADR-022](adr/ADR-022-one-number-of-stock.md)) plus a type-only
> `app.models.product_template` import for `maker` — its `CORE_EXEMPTIONS`
> entry carries both). Exemptions are granted per module and per import in
> core code; community modules cannot claim one from their manifest.

## Declaring Capabilities

<!-- validated: manifest.json -->

```json
{
  "name": "weather_widget",
  "version": "0.1.0",
  "module_type": "community",
  "inventari_min_version": "0.9.0",
  "capabilities": ["network", "filesystem"],
  "permissions": ["weather_widget:read", "weather_widget:write"]
}
```

`name`, `version` and `module_type` are required. A module from outside this repository
declares `"community"`; the registry refuses any other value from a directory it does not ship.

The `capabilities` field accepts only the four capability values listed above —
`network`, `filesystem`, `process`, `database` — enforced by the
`ManifestCapability` enum in `app/core/module_manifest_schema.py`. An unknown
capability name is **rejected at discovery** and the module stops loading.
The manifest schema is strict overall
(`extra='forbid'`), so unknown top-level fields are rejected the same way.

## Declaring Permissions

Permission strings such as `maker:write` do **not** go into `capabilities` —
they belong in the `permissions` field. Each entry is either a bare
`"<module>:<action>"` string or an object with a `key` and, optionally,
`label_key`, `description_key` and `default_roles` (for the RBAC matrix):

```json
{
  "permissions": [
    "weather_widget:read",
    {
      "key": "weather_widget:write",
      "default_roles": ["admin"]
    }
  ]
}
```

The action should be one of `read`, `write`, `manage`, `approve`, `configure`, `consume` or
`extract`. Any other needs a reason in `permission_action_exceptions`; `module validate` warns
about a key that has neither.

Keys must sit in the module's own namespace (`weather_widget:*` for a module
named `weather_widget`). Core keys (e.g. `items:read`) may be listed to
declare a dependency, but are published once in the system section of the
permission catalog, not redefined by the module.

## Validation

Run these from `backend/`: the default `--base-path` (`app/modules`) is relative to it.

```bash
# Validate a single module
python manage.py module validate --module my_module

# Export JSON Schema for IDE config
python manage.py module schema
```

`--base-path` points `validate` at another modules directory. `--allow-core` skips the safety
scan for every module it validates, not only core modules, so a clean report made with it says
nothing about imports.

The AST validator checks:
- Import statements against `FORBIDDEN_IMPORT_PREFIXES` (rejected outright)
- Remaining imports against the declared `CAPABILITY_MAP` (the matching capability is
  required, otherwise the import is rejected; `SUSPICIOUS_IMPORTS` only writes a debug log
  line and refuses nothing)
- Calls against `FORBIDDEN_CALLS = {'eval', 'exec', '__import__', 'import_module'}`
- `open()` calls when `filesystem` is not declared

### What the tools say about what they skipped

A module tool never answers "clean" over a tree it did not read. Three of them
skip files by design, and each names the skip instead of staying silent:

| Tool | Skips | Says |
|---|---|---|
| `module validate` | symlinked directories (the walk does not follow them), and dangling links | `<module>: not read (symlink): <path> -> <target>`, or the same with `(dangling: target does not exist)` |
| `module install` | every `tests/` directory, on both halves | one line per dropped path, before the copy |
| `arch lint` | symlinked directories, files the parser cannot read | `::warning ... was not read (...)` |

None of these skips is an error on its own: the link may point at something
that legitimately belongs elsewhere, tests are the author's workbench, and an
unparsable file may be a data blob with a `.py` name. What they must never be
is invisible — certification reads these reports, and a report that omits its
own blind spots is worth less than a red one.
