# Frontend Module Developer Guide

> Your module's view layer: how to register routes, inject UI slots, override labels, and test your components.

---

## Quick Start (3 steps)

### 1. Scaffold the module

```bash
make new-module
# Enter a name, e.g.  warranty_tracker
```

This creates `frontend/src/modules/warranty_tracker/` with boilerplate `module.ts`, `pages/IndexPage.tsx`, i18n files, and an empty `moduleApi.ts` — the one file other modules may import from yours ([Depending on another module](#depending-on-another-module-its-moduleapits)).

### 2. Write your page

The shell draws the page's title as its `h1`: the page hands the title over
with `useModulePageHeader()` instead of drawing a heading of its own.

<!-- typecheck: pages/IndexPage.tsx -->

```tsx
// frontend/src/modules/warranty_tracker/pages/IndexPage.tsx
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, useModulePageHeader } from "@/module-sdk";

export default function IndexPage() {
  const { t } = useTranslation("warranty_tracker");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("description") });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent>
          <p className="text-muted-foreground">{t("description")}</p>
        </CardContent>
      </Card>
    </div>
  );
}
```

### 3. Register in `module.ts`

<!-- typecheck: module.ts -->

```typescript
import { lazy } from "react";
import { Shield } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

const IndexPage = lazy(() => import("./pages/IndexPage"));

moduleRegistry.register({
  name: "warranty_tracker",
  routes: [{ path: "/warranty-tracker", component: IndexPage }],
  moduleNav: {
    basePath: "/warranty-tracker",
    items: [
      {
        path: "/warranty-tracker",
        icon: Shield,
        labelKey: "warranty_tracker:navigation.title",
      },
    ],
  },
});
```

That's it — `src/lib/moduleRegistry/moduleLoaders.ts` globs every `module.ts`
and imports one when its module is enabled; the file's side effect is the
registration. The import is lazy: a module's code reaches the browser only
for organizations that switched the module on, and never in the entry chunk.

Do **not** import your `i18n/*.json` catalogs into `module.ts`, and do not pass a
`translations` object: every `modules/<name>/i18n/<lang>.json` is discovered by the
i18n backend (`src/i18n/config.ts`) and fetched as a chunk of its own, so a
translation never travels in the entry bundle and a disabled module never costs a
reader its catalog.

### Languages: English is the only one you must ship

A module must ship `en.json` in its `i18n` folder; every other language is optional. The core
ships six languages: `en`, `pl`, `de`, `fr`, `es` and `pt` (Português (Brasil), a
community translation that may lag behind the others). A module may add a catalog
for any of them — but it cannot add a language the core does not know: the loader
skips a file such as `it.json` that is not one of the six.

A reader whose language the module does not cover sees the module in English,
key by key: a missing file and a missing key both fall back to `en.json`. The
one thing that breaks a module is shipping other catalogs and no English one,
since there is then nothing to fall back to and the screens show raw keys.
`module new-community` writes the English catalog only, and
`module new-community -l pl -l de` writes others beside it. A module that lives
in this repository (`make new-module`) is held to the five maintained languages,
`en`, `pl`, `de`, `fr` and `es`.

---

## Imports: one door into Core

`@/module-sdk` is that door. It re-exports the registry and the contract types declared in
`moduleInterfaces.ts` and `slotProps.ts`, the pre-configured API client, the
design-system components a module builds with, the hooks that answer what the
signed-in user may do, and the few helpers a module screen would otherwise
reach for. Import the name you need from there:

```typescript
import {
  Button,
  Card,
  CardContent,
  api,
  moduleRegistry,
  useCanWrite,
  useModuleQuery,
  type SlotDataMap,
} from "@/module-sdk";
```

Everything else under `@/` is Core's own business. `npm run check:boundaries`
(part of `make check-frontend`) reports a module importing a core path outside
the SDK; the modules written before the SDK existed keep the paths they already
use, and that record cannot grow. If the SDK does not export something your
module needs:

- **In a module inside this repository,** add the export to
  `frontend/src/module-sdk.ts` — an added export cannot break an existing
  module, so it is a supported change, and the next module finds it there
  instead of copying an internal path.
- **In a package you keep in your own repository,** you cannot change the
  SDK. Open an issue on the Inventari repository naming the export and what
  you use it for, and until it lands write the few lines you need inside your
  module. Do not import the internal `@/` path: `check:boundaries` reports it,
  and the path may move in a release without the notice an SDK export gets.

A module's backend half follows the same arrangement: it talks to Core through
`core_api` and never imports `app.core` internals.

### Depending on another module: its `moduleApi.ts`

A module that needs something from another module does not import the other
module's files. Three ways in, in order of preference:

1. **A slot.** The other module contributes what it knows to a place you
   render, and your module works without it. The official modules reach the
   Approvals module this way: the warehouse renders `approval_decision_panel`
   and `approval_parked_requests`, and the badge, stages and decision panel
   are drawn by Approvals when it is on.
2. **The other module's `moduleApi.ts`.** One file at the root of a module,
   `src/modules/<name>/moduleApi.ts`, re-exporting what that module offers the
   modules that declare it in `requires`. `check:boundaries` lets exactly this
   path through and counts every other path into the module as an edge. The
   owner documents each name there and treats removing or renaming one as a
   breaking change. The warehouse publishes its catalogue search, its product
   search hook and its document status badge for purchase orders:

   ```typescript
   import { documentsProductsApi } from "@/modules/warehouse/moduleApi";
   ```

   Add a name to a module's `moduleApi.ts` when a second module needs it, never
   to save a path. `make new-module` writes the file empty, so the module's
   first dependant finds the door rather than reaching past it. A module you depend on only optionally is reached through a
   slot, not through its `moduleApi.ts` — an import cannot be optional.
3. **Your own screens.** Build what you need in your module, from `@/module-sdk`.

---

## API Client (`api`)

The frontend ships a pre-configured Axios instance. Import it and call standard Axios methods:

```typescript
import { api } from "@/module-sdk";

// GET
const { data: items } = await api.get("/my-module");

// POST
const { data: created } = await api.post("/my-module", { name: "Test" });

// PATCH
await api.patch(`/my-module/${id}`, { status: "active" });

// DELETE
await api.delete(`/my-module/${id}`);
```

**Behaviour:**
- `baseURL` is `/api/v1` — all paths are relative to the API root.
- `Authorization: Bearer <token>` is attached automatically from in-memory token store.
- `Accept-Language` header is set from the current i18next language.
- **401 handling:** on the first 401, the client attempts a silent token refresh via `/auth/refresh`. If refresh succeeds, the original request is retried. If the server refuses the refresh, or has no session to refresh, the token is cleared, the `auth:logout` event is dispatched and the promise rejects. If the refresh gets no answer at all (a network failure, an outage), the session is kept and the promise rejects.
- **Errors:** non-401 errors propagate as rejected Axios promises to the calling hook/component. The client itself shows no toast — handle errors in your `useMutation` / `useQuery` `onError` callbacks, or read `mutation.error` where the screen can show it.

**Showing the server's message.** A refusal a person can act on (a `409`, a `404`, a `422`) carries a sentence in the reader's language in the response wherever the backend has a translation for it; a `422` keeps pydantic's English wording for a constraint the catalogue does not cover. `extractApiError` returns it, or the fallback you pass when the response has none, as for a `5xx` or a lost connection:

```typescript
import { extractApiError } from "@/module-sdk";

{createItem.isError && (
  <p role="alert" className="text-sm text-on-danger">
    {extractApiError(createItem.error, t("messages.createFailed"))}
  </p>
)}
```

The `example_widgets` page shows it on a failed create.

**With TanStack Query (recommended):**
```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "@/module-sdk";

interface MyItem { id: string; name: string }

const { data, isLoading } = useQuery<MyItem[]>({
  queryKey: ["my-module", "list"],
  queryFn: () => api.get("/my-module").then(r => r.data),
});
```

> For module-specific hooks, create a dedicated `hooks/` file (e.g. `hooks/useMyModule.ts`) rather than calling `api` inline in components. Use `useModuleQuery` from `@/module-sdk` to auto-disable when the module is off.

---

## `FrontendModule` Interface Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | Yes | Unique module identifier. Must match backend `manifest.json` name. |
| `routes` | `ModuleRoute[]` | Yes | React Router routes registered by this module. |
| `moduleNav` | `ModuleNavConfig` | No | Navigation tabs: the desktop bar rendered by `ModuleShell`, the phone bar by `AppShell`. |
| `slots` | `SlotContribution[]` | No | UI components injected into predefined core slots. |
| `launcher` | `LauncherConfig` | No | Tile shown in the App Store / Launcher grid. |
| `settingsSections` | `SettingsSection[]` | No | Extra pages injected into Settings sidebar. |
| `navOverrides` | `NavOverride[]` | No | Replace/hide navigation items per organization. |
| `standalone` | `StandaloneDeclaration` | No | Declares how the module can run as the single focus module. |
| `backgroundFeatures` | `Record<string, ComponentType>` | No | Route-free surfaces offered to focused modules. |
| `i18nOverrides` | `Record<lang, Record<key, string>>` | No | Override core translations at runtime (keys as `ns:path`; see the gate test). |
| `theme` | `{ cssVariables: Record<string, string> }` | No | Organization-scoped CSS variables. |
| `labelPurpose` | `LabelPurposeConfig` | No | Offers a module-owned purpose for generated and scanned labels. |
| `bulkActions` | `Omit<BulkAction, "moduleName">[]` | No | Actions shown when multiple items are selected (rendered by `ItemsBulkActionBar.tsx`). |
| `validationRules` | `ValidationRule[]` | No | Validators contributed to core forms (`item_create`, `item_edit`). Run on submit; core errors win; a throwing rule is logged and skipped. See MODULES_GUIDE "Validation Rules". |
| `columnContributors` | `ColumnContributor[]` | No | Additional columns for the Items list table. |
| `listFilterContributors` | `ListFilterContributor[]` | No | Filter chips for the Items list; the module answers with the template ids the chip narrows to. |
| `documentColumnContributors` | `DocumentColumnContributor[]` | No | Columns for the warehouse documents lists (History and Documents), keyed by document — see "Contributions to the warehouse documents". |
| `documentFilterContributors` | `DocumentFilterContributor[]` | No | Filters for the documents lists, answered on the server by the module's registered filter. |
| `documentActionContributors` | `DocumentActionContributor[]` | No | Buttons for a document's action row. |
| `useActionItems` | `() => ActionItem[]` | No | Hook returning launcher action items ("Things to do"). |
| `useStatusBadge` | `() => { count: number; labelKey: string; failed?: boolean } \| null` | No | Hook returning a badge count or read failure for the launcher tile; the tile translates `labelKey` with `{ count }`. |
| `statusBadgePermission` | `string` | No | The read the badge's endpoint asks for; the launcher calls `useStatusBadge` only for a role holding it. Omitted, every role is asked. |
| `searchProvider` | `SearchProvider` | No | Supplies command-palette results while the module is enabled. |

---

## Navigation with `moduleNav`

`moduleNav` describes the navigation tabs of your module: the desktop bar `ModuleShell` renders, and the phone bar `AppShell` renders, when the user is inside your module.

```typescript
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const AssetsPage = lazy(() => import("./pages/AssetsPage"));

moduleRegistry.register({
  name: "equipment",
  routes: [
    { path: "/equipment", component: DashboardPage },
    { path: "/equipment/assets", component: AssetsPage },
  ],
  moduleNav: {
    basePath: "/equipment",              // the URLs that belong to this module
    items: [
      {
        path: "/equipment",              // the overview
        icon: LayoutDashboard,
        labelKey: "equipment:nav.overview",
        titleKey: "equipment:dashboard.title",    // Optional page <h1>
        subtitleKey: "equipment:dashboard.subtitle", // Optional subtitle
        order: 10,
        showOnMobile: true,
        showOnDesktop: true,
      },
      {
        path: "/equipment/assets",       // the assets list
        icon: Monitor,
        labelKey: "equipment:nav.assets",
        titleKey: "equipment:list.title",
        order: 20,
      },
    ],
  },
});
```

**Rules:**
- Item paths are absolute (`/equipment/assets`): the shell links to each one as written. `basePath` says which URLs the module owns; it is not a prefix.
- Every `moduleNav` item path must have a matching entry in `routes`.
- `ModuleShell` renders the page title and subtitle from `titleKey` / `subtitleKey` (the title falls back to `labelKey`); a back arrow appears when the page sets `backTo` through `useModulePageHeader()`.
- Never render your own `<h1>` inside page components — use `useModulePageHeader()` instead.

---

## UI Slots

Slots let you render React components inside the core application without editing core files.

### Typed slots (recommended)

Type the component's `data` with the slot's entry in `SlotDataMap`, and register
it wrapped in `slotComponent()`. The registry keeps every slot's component under
one type, `ComponentType<{ data: unknown }>`, and a component that asks for a
narrower `data` is not assignable to it — the bare component fails
`tsc --noEmit` with TS2322. `slotComponent()` stores it under that type once
the compiler has checked your props; the slot hands the component the data of
the slot it was registered into.

<!-- typecheck: components/ExtraFields.tsx -->

```tsx
import { moduleRegistry, slotComponent, type SlotDataMap } from "@/module-sdk";

const ExtraFields = ({ data }: { data: SlotDataMap["item_edit_extra"] }) => (
  <div>
    Custom fields for {data.item.name}
    <input
      value={String(data.formData["custom_field"] ?? "")}
      onChange={(e) => data.handleInputChange("custom_field", e.target.value)}
    />
  </div>
);

moduleRegistry.register({
  name: "my_feature",
  routes: [],
  slots: [
    { slot: "item_edit_extra", component: slotComponent(ExtraFields), priority: 10 },
  ],
});
```

### Complete Slot Reference

| Slot name | Render location | Props shape | Status |
|---|---|---|---|
| `item_edit_extra` | Item Edit modal — below standard fields | `item`, `formData`, `handleInputChange(field, value)`, `storageType?`, `requestLeave?` | Active |
| `quick_action_extra` | Quick Actions panel per item | `item` | Active |
| `stock_action_extra` | Stock Action modal (barcode scan) | `barcode`, `template` | Active |
| `global_notifications` | Global notification layer | `{}` | Active |
| `items_page_header_extra` | Items list page — above the table | `{}` | Render site only (extension point) |
| `dashboard_widgets` | Dashboard — widget grid | `{ organizationId }` | Render site only (extension point) |
| `quick_add_product_info` | Quick-add form — product info | `formData`, `storageTypeCode?`, `categoryContextTag?` | Active |
| `dashboard_replenish_action` | Dashboard — the attention card's actions, beside "view all" | `onOpen` | Active |
| `dashboard_replenish_modal` | Dashboard replenishment modal | `isOpen`, `onClose` | Active |
| `dashboard_activity_aside` | Dashboard — beside the recent moves | `{}` | Active |
| `storage_item_edit_modal` | Storage detail — item edit modal | `itemId`, `onClose` | Active |
| `item_detail_extra` | Product detail page — below the movement history | `item` | Active |
| `recipe_cook_for_stock` | Recipe detail page — the "cook a batch for stock" sheet | `open`, `onClose`, `recipe` | Active |
| `shopping_list_add_item` | Shopping list — add item modal | `listId`, `onClose`, `onSuccess` | Active |
| `settings_ai_module_config` | Settings → AI tab | `{}` | Render site only (extension point) |
| `settings_module_card` | App Store page (`/apps`) — standalone card | `{}` | Render site only (extension point) |
| `storage_detail_extra` | Location page → Settings tab — below the warehouse strip | `storageId`, `storageTypeCode` (may be undefined) | Render site only (extension point) |
| `storage_tree_row_extra` | Location tree — beside each location's name | `storageId` | Active |
| `storage_warehouse_strip` | Location page → Settings tab — below the location's settings | `storageId`, `storageName`, `fullPath`, `sequence` | Active |
| `storage_moves` | Location page → Moves tab | `storageId`, `storageTypeCode` (may be undefined) | Active |
| `document_detail_extra` | Document detail page — below the lines and totals | `documentId`, `documentStatus`, `metaData?`, `saveMetaData?` | Active |
| `document_detail_line_extra` | Document detail page — under each line, in the table and the phone's cards | `documentId`, `documentStatus`, `line`, `saveMetaData` | Render site only (extension point; `examples/lot_certificates` registers one) |
| `document_form_extra` | Receive, Issue and the document form — among the document-level fields | `action`, `documentType`, `partnerId`, `lines`, `metaData`, `setMetaData`, `registerBeforeSubmit` | Render site only (extension point) |
| `document_line_form_extra` | Receive, Issue and the document form — under each line. Receive on the desktop only, in a row of its own below the line's lot and expiry panel (a phone counts its goods on the receiving session instead); Issue and the document form on desktop and phone | `action`, `documentType`, `line`, `setMetaData`, `registerBeforeSubmit` | Render site only (extension point; `examples/lot_certificates` registers one) |
| `approval_status_badge` | Document/resource detail — approval status | `targetType`, `targetId`, `approval?`, `requestModule?`, `requestConsequence?`, `onApprove?`, `onRequest?`, `onReject?` | Active |
| `approval_request_badge` | A queue card or list row of a target module — the state of an approval request | `status` | Active |
| `approval_decision_panel` | A queue card of a target module — the request's progress through its stages and the approve / reject panel | `approval`, `onApprove(request, notes?)`, `onReject(request, notes)` | Active |
| `approval_parked_requests` | Above a target module's approval queue — the open requests parked at a stage nobody can decide | `targetType`, `targetHref(targetId)` | Active |
| `document_approval_setup_notice` | The warehouse's document approval settings — what the threshold and types do given the workflows that exist | `approvalRequested` | Active |

> **Status semantics — what does "Active" vs "Extension point" mean for you?**
>
> Both statuses are **fully functional render sites** — the Core renders a `<TypedSlot>` at that location regardless. The difference is only about reference implementations:
>
> - **Active** = at least one module under `frontend/src/modules/` currently registers a component into this slot. You can look at an existing contributor for a working example.
> - **Render site only (extension point)** = Core renders the `<TypedSlot>` placeholder, but no module under `frontend/src/modules/` fills it yet. The slot is fully wired and ready — your module can register into it and it will render. Think of these as reserved extension points that third-party modules can populate without touching Core.
>
> In practice: **you can register into any slot listed above**, regardless of status. The slot will render your component. "Extension point" just means "no module under `frontend/src/modules/` fills it yet"; where the status names an example outside that tree, copy from it.
>
> **SlotDataMap types** live in `frontend/src/lib/moduleRegistry/slotProps.ts`. Import `type { SlotDataMap }` for compile-time checking.

### A field of your own on a document

The two document form slots are how a module adds a field to a warehouse
document. `line.metaData` (or, in `document_form_extra`, `metaData`) holds
what the document stores under each module's name; your component reads its
own key and writes it back with `setMetaData("<your_module>", values)` —
`null` removes it. The value is sent with the document on every post or save,
and an edited draft sends back every module's fields with it. On the document
page, `saveMetaData(module, values)` writes to the saved document at once (a
promise) — the way to fill a field on a confirmed document before it is
posted; it is refused once the document is completed or cancelled. Make the field
required where it matters with your module's pre-post check, which reads the
same `meta_data`; see `docs/subsystems/CROSS_MODULE_EXTENSION.md`, Pattern 4,
and the worked example in `docs/MODULE_ADVANCED_GUIDE.md`.

<!-- typecheck: components/GradeField.tsx -->

```tsx
import { Input, moduleRegistry, slotComponent, type SlotDataMap } from "@/module-sdk";

const GradeField = ({ data }: { data: SlotDataMap["document_line_form_extra"] }) => (
  <Input
    label="Grade"
    value={String(data.line.metaData.my_feature?.grade ?? "")}
    onChange={(e) => data.setMetaData("my_feature", { grade: e.target.value })}
  />
);

moduleRegistry.register({
  name: "my_feature",
  routes: [],
  slots: [{ slot: "document_line_form_extra", component: slotComponent(GradeField) }],
});
```

### Contributions to the warehouse documents

The items list takes a module's columns and filter chips
(`columnContributors`, `listFilterContributors`); the warehouse documents take
the same three kinds of contribution, keyed by document. Each is shown while
your module is enabled for the organization, and each receives the document
as a `DocumentView` — its id, type, number, status, its `metaData` and its
lines with theirs — the shape a module that keeps its own fields on a
document needs to read them back.

| Field | Where | What it does |
|---|---|---|
| `documentColumnContributors` | The documents lists, History and Documents, one value per row | `render(doc)` draws the value, `label` names it (neither list has a header row, so the name is printed with each value), and `hasValue(doc)` lets the list leave the column out when no row on the page fills it. |
| `documentFilterContributors` | The documents lists — a chip on History, and in the Documents filter panel | `key` is the name your backend registered with `warehouse_api.register_document_filter(module, key, provider)`; while it is on, the list asks the server for `?module_filter=<module>:<key>` and the provider answers which of your fields a line must carry. The narrowing is the server's, so the count and the paging stay true. |
| `documentActionContributors` | A document's action row, after its own actions | `isAvailable(doc)` says whether the button belongs on this document; `run(doc)` is the press. It is offered to a reader who may write documents; a rejection shows its message (throw a `ReadableError`, or let your API's 4xx through), and the page reads the document again once `run` resolves. |

```ts
moduleRegistry.register({
  name: "lot_certificates",
  routes: [],
  documentColumnContributors: [
    {
      key: "certificate",
      label: "lot_certificates:column.certificate",
      hasValue: (doc) => certificateNumbers(doc).length > 0,
      render: (doc) => certificateNumbers(doc).join(", "),
    },
  ],
  documentFilterContributors: [
    { key: "certified", label: "lot_certificates:filter.certified" },
  ],
  documentActionContributors: [
    {
      key: "file",
      label: "lot_certificates:action.file",
      isAvailable: (doc) =>
        doc.type === "IN" && ["DRAFT", "CONFIRMED"].includes(doc.status),
      run: async (doc) => {
        await fileCertificates(certificateNumbers(doc));
      },
    },
  ],
});
```

The whole module — these three, the line field, the receiving rule and the
pick order — is the worked example in `docs/MODULE_ADVANCED_GUIDE.md`
("Extending the warehouse"), and its source is `examples/lot_certificates/`.

---

## App Store / Launcher Tile

Register a tile in the Launcher grid so administrators can discover and enable your module.

```typescript
moduleRegistry.register({
  name: "my_feature",
  routes: [],
  launcher: {
    displayName: "my_feature:launcher.title",
    description: "my_feature:launcher.description",
    icon: Shield,
    category: "business",     // "core" | "business" | "analytics" | "integrations" | "system"
    color: "bg-blue-500",     // Use design tokens: accent-*, primary-*, blue-*, amber-*
    order: 20,
    required: false,          // true = tile always shows, can't deactivate
    hidden: false,            // true = invisible infra module (e.g. "printing")
  },
});
```

---

## Settings Sections

Add a dedicated settings page for your module inside the Settings shell.

```typescript
const MySettingsPage = lazy(() => import("./pages/SettingsPage"));

moduleRegistry.register({
  name: "my_feature",
  routes: [],
  settingsSections: [
    {
      title: "my_feature:settings.title",
      path: "my-feature",        // → /settings/my-feature
      icon: Settings,
      component: MySettingsPage,
    },
  ],
});
```

---

## Core Overrides (White-Labeling)

### `navOverrides` — Relabel or hide navigation

```typescript
moduleRegistry.register({
  name: "library",
  routes: [],
  navOverrides: [
    { targetPath: "/inventory/items", icon: BookOpen, labelKey: "library:nav.books" },
    { targetPath: "/shopping-lists", hidden: true },
  ],
});
```

### `i18nOverrides` — Change terminology at runtime

```typescript
moduleRegistry.register({
  name: "library",
  routes: [],
  i18nOverrides: {
    en: {
      "inventory:nav.items": "Catalogue",
      "items:title": "Catalogue",
    },
    de: {
      "inventory:nav.items": "Bibliothekskatalog",
      "items:title": "Bibliothekskatalog",
    },
    // fr, es, pl — optional. Declare the languages you have terms for; a
    // reader in a language you skip keeps the core's own wording.
  },
});
```

Keys carry their namespace: `"inventory:nav.items"` overrides the
`inventory` bundle, a key without a prefix overrides `common`. The override
must name the key the reader actually calls `t()` with — the sidebar reads
`inventory:nav.items`, not `common:navigation.items`. The
`i18nOverridesGate` test fails the build when an override targets a key that
is missing from the shipped bundles or that nothing in `src/` reads.

**A rename carries the page it opens.** Renaming a navigation tab without the
page title that tab leads to puts one concept under two names — the reader
follows "Assets" and lands on "Products". The equipment module used to do
exactly that; it declares no `i18nOverrides` today, and
`lib/moduleRegistry/navLabelVocabulary.test.ts` holds the four inventory tab and
page pairs (`inventory:nav.items` with `items:title`, and three more) to one word
in every maintained language, whichever enabled module renames them.

> Original translations are restored automatically when the module is disabled.

### `theme` — Organization-scoped colors

```typescript
moduleRegistry.register({
  name: "equipment",
  routes: [],
  theme: {
    cssVariables: {
      "--color-accent-500": "59 130 246",
      "--color-accent-600": "37 99 235",
    },
  },
});
```

---

## Launcher Hooks: `useActionItems` & `useStatusBadge`

Provide dynamic content for the Launcher: `useStatusBadge` feeds the badge on a tile, and `useActionItems` feeds the "Things to do" feed.

### `useActionItems` — "Things to do" feed

```typescript
moduleRegistry.register({
  name: "warranty_tracker",
  routes: [],
  useActionItems: () => {
    // Asked for every enabled module: only a role holding the read may ask.
    const mayRead = useHasPermission("warranty_tracker:read");
    const { data } = useQuery({
      queryKey: ["warranties", "expiring"],
      queryFn: fetchExpiring,
      enabled: mayRead,
    });
    if (!mayRead || !data) return [];
    return [{
      id: "warranties-expiring",
      labelKey: "warranty_tracker:expiringSoon",
      icon: AlertTriangle,
      severity: "warning",
      linkTo: "/warranty-tracker",
      count: data.length,
    }];
  },
});
```

### `useStatusBadge` — Tile badge count

```typescript
moduleRegistry.register({
  name: "warranty_tracker",
  routes: [],
  useStatusBadge: () => {
    const { data } = useQuery({ queryKey: ["warranties", "count"], queryFn: fetchExpiringCount });
    if (!data) return null;
    return { count: data, labelKey: "warranty_tracker:expiringSoon" };
  },
  // The read the badge's endpoint asks for: the launcher calls the hook only
  // for a role holding it.
  statusBadgePermission: "warranty_tracker:read",
});
```

> Both hooks run inside a React component context — you can use `useQuery`, `useState`, etc. They must handle loading/error states internally (return `[]` or `null` while loading); the tile shows no badge until the hook answers, and nothing times it out. Both hand over an i18n key in full form, never words: the feed translates an action item's `labelKey` with its `labelValues`, the tile a badge's `labelKey` with `{ count }`, so a plural form (`expiringSoon_one` / `_other`) follows the number. A failed read returns the same shape with `failed: true`: for `useStatusBadge`, `{ count: 0, labelKey, failed: true }`, and the tile says the badge could not be read. The launcher shows a tile for every enabled module, whatever the signed-in role may read, so a role is asked only for what it may read: a badge names the read its endpoint asks for in `statusBadgePermission`, and the launcher calls `useStatusBadge` only for a role holding it (omitted, every role is asked); an action-items hook asks its endpoint only when `useHasPermission` grants the read, and returns `[]` otherwise. A refusal the role was always going to meet is not a failed read, and the tile and the feed must not say it is.

**A badge is a reader, not a poller.** Every tile on the launcher mounts its module's hook, so each query a badge adds is one more request on the screen people leave open on a tablet all day. Read the query the module's own screen already owns, under the same key, and the launcher, the dashboard and the list share one request and one cache entry: export the module's `queryKey` and `queryFn` from one place and use them in both. (Inventory's badge reads the attention counts the dashboard heading and the statistics card read.) Give the hook its own `refetchInterval` only for a read no screen of the module fetches, and never for a heavy aggregate: a long `staleTime` with writes invalidating the key keeps the badge fresh without a loop. The same goes for a feed: when a socket pushes the change (notifications), poll only while the socket is down.

### `useRecordVisit` — "Recently visited"

The launcher's **Recently visited** panel and the command palette's recent list show the record
pages a person opened. A page that shows one record a person comes back to — Core's product page,
an equipment asset, a recipe — adds it with one call, made before any early return:

```typescript
import { useRecordVisit } from "@/module-sdk";

const { data: warranty } = useWarranty(id);
useRecordVisit("warranty_tracker", warranty); // { id, name } once loaded, undefined before
```

The entry is stored under the page's own address and named by the record's `name`; the list names
the module the way its launcher tile does. Lists and forms do not call it.

---

## Testing a Frontend Module

We use **Vitest** + **React Testing Library**.

### Recommended layout

```
frontend/src/modules/warranty_tracker/
├── pages/
│   ├── IndexPage.tsx
│   └── IndexPage.test.tsx          ← colocated test
├── components/
├── hooks/
└── module.ts
```

### Example test

The page's title is not in what the page itself renders: the page hands it to
the shell through `useModulePageHeader()` (step 2), and the shell draws it. A
test renders the page without the shell, so it puts a `PageHeaderContext`
around the page and checks what the page handed over. Every module's
`i18n/*.json` is loaded by the test setup, and English is the test language.

<!-- typecheck: pages/IndexPage.test.tsx -->

```tsx
// frontend/src/modules/warranty_tracker/pages/IndexPage.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PageHeaderContext } from "@/module-sdk";
import IndexPage from "./IndexPage";

function renderPage(setHeader = vi.fn()) {
  // Minimal QueryClient for tests (no retries)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
          {children}
        </PageHeaderContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>
  );
  render(<IndexPage />, { wrapper });
  return setHeader;
}

describe("IndexPage", () => {
  it("hands the module title to the shell", () => {
    const setHeader = renderPage();
    expect(setHeader).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Warranty Tracker" }),
    );
  });

  it("renders the description", () => {
    renderPage();
    expect(screen.getByText("Warranty Tracker module — add your description here.")).toBeInTheDocument();
  });
});
```

### Running tests

```bash
cd frontend
npm run test:run              # CI mode
npm test                      # watch mode: re-runs the tests you change
```

### Mocking the module registry

You rarely need to mock `moduleRegistry` directly. If your component consumes module context, mock hooks rather than the registry:

```typescript
vi.mock("@/modules/my_feature/hooks/useMyFeature", () => ({
  useMyFeature: () => ({ data: mockData, isLoading: false }),
}));
```

---

## Best Practices

1. **Lazy load everything.** Use `lazy(() => import("..."))` for pages and heavy components.
2. **Use `@/` imports.** Never use `../../` relative paths beyond one directory.
3. **Never hardcode strings.** Always use `t("namespace:key")` from `react-i18next`.
4. **Use UI components.** Import `<Button>`, `<Card>`, `<Input>`, `<Badge>` from `@/module-sdk` instead of raw HTML.
5. **Keep functions small.** ESLint enforces `complexity` ≤ 25 and `max-lines-per-function` ≤ 300; it sets no line limit per file. A component with more than one responsibility splits into sub-components inside `modules/{name}/components/`.
6. **Never use `any`.** Prefer `unknown` + type guards or proper interfaces.
7. **Guard module hooks.** Check `enabledModules.includes("module_name")` (from `useModules()`, exported by `@/module-sdk`) before calling module-specific API hooks.
8. **Write through `useAppMutation`.** The SDK exports it; it reports a failed write to the reader, which a bare `useMutation` does not.

---

### Background features in focus mode

A standalone module may declare `standalone.backgroundFeatures` as an array of
`{ provider, feature, labelKey }`. Each provider registers a matching component in
its `backgroundFeatures` map. The shell resolves only explicitly declared features
from enabled providers and opens them in a sheet over the focused module. Provider
components must be embedded surfaces: no page headers or links into provider routes.
They mount only while the sheet is open, so background reads do not run on every page.

The backend module declares additional providers in `focus_background_modules`.
The existing focus profile planner expands those providers' normal dependencies,
keeps them enabled, and restores the pre-focus snapshot on exit. This declaration
is specific to focus; optional integrations remain optional in ordinary workspaces.
Recipes uses stock from inventory and the active shopping list, while ingredient
coverage, product linking/creation and adding shortages remain inline recipe actions.

---

*For the backend counterpart, see [MODULES_GUIDE.md](../MODULES_GUIDE.md).*
