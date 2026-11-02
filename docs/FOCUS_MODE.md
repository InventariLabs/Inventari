# Showing a single module

Settings → My modules (administrators only) offers enabled modules whose frontend
module declares `standalone`, one `Show only <module>` switch each. The preview,
apply and exit calls are admin endpoints (`backend/app/api/modules.py`). Showing a single
module enables the module's backend dependency closure,
hides other modules from the launcher and switcher, and preserves Settings as
the way out. Switching the control off restores the previously enabled set and keeps the
focused module and its dependency closure on, also when the mode was chosen
at first run, before the module was ever enabled. Each module the exit
switches is recorded in the audit log. No data is removed.

A declaration explicitly adopts or renounces labels, scanning, statistics,
stock takes and archives. `keepCoreNav` keeps the inventory sections needed to
finish the focused workflow. These pages retain their URLs and APIs while
using the focused module's banner and navigation.

## Module decisions

This audit covers every directory under `frontend/src/modules`. A launcher tile
alone does not make a module a standalone product. The planner may preserve manually enabled modules in the background. Optional
integrations are not required for the workflows listed here; a direct link to
a background module keeps that module's own shell. Inline background features
are a separate extension of focus mode.

| Module | Decision | Reason / kept inventory sections |
| --- | --- | --- |
| `announcements` | Not standalone | Shell notifications and banners have no independent workspace. |
| `api_keys` | Not standalone | Organization administration for API consumers (keys belong to one organization), reached through Settings. |
| `approvals` | Needs other modules; not offered yet | Requests originate in documents, orders or equipment; focusing on approvals alone disables their target workflows. |
| `warehouse` | Standalone with core | Receipts, dispatches, transfers and corrections own their lifecycle; keep products, locations, categories, stock and movements. Approvals are optional. |
| `equipment` | Standalone as is | Owns asset lifecycle and its own asset screens; its location screen reads the Core locations. Adopts labels and scanning; keeps no inventory section. |
| `example_widgets` | Not standalone | Developer demonstration of extension slots, not an end-user product. |
| `inventory` | Not a separate focus target | Built-in inventory workspace combines always-on backend features; there is no toggleable backend module named inventory. |
| `launcher` | Not standalone | Workspace navigation, not a business workflow. |
| `maker` | Standalone with core | Owns recipes and production runs; keep products, locations, categories, stock and movements. Creating a recipe from a culinary recipe (a one-way snapshot) is optional. |
| `nutrition` | Not standalone | Adds nutrition fields and actions to product screens; has no independent pages. |
| `onboarding` | Not standalone | Installation setup shared by all products; no module manifest. |
| `partners` | Not standalone | A contact directory that documents and orders draw on; alone it is one list with no work around it. A module can be the whole app when someone can spend a working day in it, not when it only serves other modules. |
| `printing` | Not standalone | Always-on label infrastructure; scanning resolves the labelled entity in its owning workflow. |
| `purchase_orders` | Needs documents; not offered yet | Receiving creates and opens a document; the required warehouse module is enabled in the background but has no visible navigation in order focus. Await navigation to background modules. |
| `recipes` | Standalone as is | Keeps no inventory section in its navigation: stock and the shopping list are offered as background features instead, and production is not among them. Its declaration is in `frontend/src/modules/recipes/module.ts` and is pinned by `standaloneGate.test.ts`. |
| `settings` | Not standalone | Shared installation administration and focus exit. |
| `shared` | Not standalone | Shared components and hooks; no module manifest or independent workflow. |
| `shopping_lists` | Standalone with core | Owns lists, lines and purchased state; keep products, locations and categories for stock suggestions and pantry management. Recipe and order integrations are optional. |
| `spaces` | Not standalone | Storage components are surfaced by inventory: its four `/inventory/locations` routes render under the inventory shell (`shell: "inventory"`); no backend focus target. |
| `stats` | Not standalone | Always-on inventory analytics, not a toggleable focus target. |
| `stock_takes` | Not standalone | An occasional activity over stock that another module manages; focusing on it keeps products, locations, stock and movements, so it narrows almost nothing. An organization already focused on it keeps working: the counting routes render under the inventory shell and My modules shows the focus and lets the admin leave it. |
| `vision` | Not standalone | Photo recognition assists product entry and nutrition scanning; no independent screens. |
| `webhooks` | Not standalone | Installation integration plumbing; subscriptions need other workflows to produce events. |

The exact eligible list is pinned by
`frontend/src/lib/moduleRegistry/standaloneGate.test.ts`, using the same registry
query as My modules. Its tests also check every declaration's core decisions,
valid kept sections, and the stock-take home/counting navigation.
