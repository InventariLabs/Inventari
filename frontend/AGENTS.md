# Frontend Conventions (frontend/AGENTS.md)

Applies to everything under `frontend/` — read together with the root [`AGENTS.md`](../AGENTS.md)
(workflow, branches, gates). **MANDATORY** before creating or modifying a UI component: §0 of
[`UI_GUIDELINES.md`](UI_GUIDELINES.md) ("Read this first"), then the sections it names for what you touch.

## 🎨 Frontend Engineering Standards (React / TypeScript)

### 1. The "No-Any" Policy (Type Safety)
`any` is strictly forbidden in new code. Use `unknown` if the type is truly dynamic, or proper Interfaces/Types.

- **i18next casting:** Prefer static keys (`t('common:actions.save')`) or ``t(`status.${status}` as const)`` — never `t(key as any)`.
- **Form Data:** Avoid `parseFloat(value as any)`. Use `Number(value)` or `parseFloat(String(value))`.
- **API Responses:** Always define an Interface for API data. Use `useQuery<Item[]>(...)` instead of `useQuery<any[]>(...)`.

#### Hand-written types and the wire

`src/types/api-generated.ts` is generated from the backend's OpenAPI schema
and is the truth about what arrives. The hand-written interfaces in
`src/types/*` are older and far more widely imported, and nothing used to
compare the two — so `tsc` stayed green over declarations that were simply
wrong. Both directions have cost real defects: `DocumentLine.quantity` typed
`number` where the backend serialises a Decimal as text (an addition became
string concatenation, and two plus three read `2.0003`), and a category
field whose hand-written copy narrowed a plain string to three food values
(every comparison against a category from another vertical answered "no",
silently).

Three states, in order of preference:

1. **Alias.** `export type Item = components["schemas"]["Item"]` — the
   schema's own name, the schema's own shape, nothing in between. Nothing can
   drift; `types/inventory.ts` has the precedent. This is where a type ends up,
   and a type whose name **is** a key of `components["schemas"]` must be this:
   `npm run check:api-types-mirror` (part of `make check-frontend`) fails on a
   new declaration that keeps a schema's name and is not that bare alias. Its
   baseline, `scripts/api-types-mirror-baseline.txt` (one `path::Name` per
   line), is empty: every such copy has been converted. Never add a line.
   The same gate refuses the copy under the schema's name **minus its suffix**
   — an interface `AiConnection` beside `AiConnectionDTO` (`DTO`, `Response`,
   `Out`, `Read` and `Schema` are the suffixes it strips). That one is an alias
   of the suffixed schema, a `Omit<…>`/`Pick<…>` of it with the difference
   stated in a comment, or an interface carrying `@mirrors` for it; a form's
   working shape takes a name of its own (`AiConnectionDraft`).
2. **Mirror.** A hand-written interface whose doc comment carries
   `@mirrors components["schemas"]["XDTO"]`. `npm run check:mirrors` (part
   of `make check-frontend`) compares the two field by field — presence,
   optionality, and the primitive type where both state one — and fails on a
   difference. Use this when the screens need a shape the alias cannot give
   yet. It is for a type named something **other** than the schema's — a
   working shape under its own name — which is why it and the rule above do
   not overlap.
3. **Neither.** A type that is not a copy of one schema — a list response
   with computed counts, a form's own working shape. Say so in the comment,
   the way `LabelScanView` in `types/inventory.ts` does: tagging it `@mirrors` would make the check
   meaningless, and silence would leave the next reader guessing.

The direction of travel is 3 → 2 → 1: a mirror is a stop on the way, never
the destination. When you touch a hand-written type, ask whether the alias
works now.

**UI-only types stay hand-written.** `…Props`, `…State`, `…Options`, a form's
working state, a list response with computed counts — these are the frontend's
own vocabulary, not a schema in different words. They carry no schema name, so
neither check sees them. When one *does* collide with a schema's name, rename
it; do not put a frontend shape under a wire name to keep the gate quiet.

**Quantities and money follow `docs/TECHNICAL_DECISIONS.md` §18.** A stock
quantity or an amount of money crosses the API as a string, never a JSON
number, and §18 lists what deliberately stays a float (a product's unit weight,
the reorder threshold, the analytics estimates). An alias cannot get this
wrong; a hand-written copy can, and `DocumentLine.quantity` was exactly that
mistake.

### 2. UI Development Workflow
Follow the **"Component-First, Isolation-Second"** pattern to minimize visual bugs:

1.  **Atomic Design:** Build small, stateless **generic** components in `src/components/ui/` first.
2.  **Size & Complexity:** No per-file LOC limit; ESLint guards functions — `complexity` ≤ 25 and
    `max-lines-per-function` ≤ 300 (see `frontend/eslint.config.js`). A component nearing ~400 lines usually has
    more than one responsibility — split it or move logic into hooks. Baseline overrides in `eslint.config.js`
    are grandfathered, and `scripts/function-baseline.json` freezes each one of them per function:
    `check:function-baseline` (part of `make check-frontend`) refuses a frozen function that grew, a new
    function above the limit in a listed file, and an entry that silences nothing. Only `--write-baseline`
    changes the numbers, never a hand edit — new code must comply.
    - ⛔ **Sub-components go into the module directory** (`src/modules/<module>/components/`), **NEVER** into `src/components/`.
3.  **Module-First File Placement:** New business components, pages, and hooks MUST live in `src/modules/<module>/`.
    `src/components/` is **exclusively** for generic Design System components with zero business-logic imports —
    if it is not usable by *any* module, it does not belong there.
    - **`src/modules/settings/` and `src/modules/shared/` are shared layers, not vertical modules.**
      `settings` owns the installation-level hooks and components every module may import
      (`useOrganization`, `useModuleSettings`, `ModuleSettingsForm`, `useProfileLabels`, `useAiConnections`,
      `PurposeBindingSelect`) — import them, don't duplicate them. `useModules` is not among them: it
      lives in `src/contexts/ModulesContext.tsx`. Everything else under `settings/` is
      its own screens, and stays off-limits like any other module's internals.
4.  **Visual Consistency:** Strictly follow `UI_GUIDELINES.md` — `success-*` (never `emerald-*`, never `accent-*`) for success states, `<Button>`/`<Input>`/`<Card>` from `ui/` instead of raw HTML tags, and the Z-Index Layer System (§4.1).
5.  **Responsive-First:** A new modal or sheet is a `<Sheet>` (UI_GUIDELINES §4.3), which is a bottom sheet on a phone and centred on a desktop by itself.

### 3. Server State Management (TanStack Query)
- **Hooks over Inline Queries:** Move `useQuery` and `useMutation` logic from Components to dedicated hooks (e.g., `src/modules/recipes/hooks/useRecipes.ts`).
- **Invalidation:** Always use `queryClient.invalidateQueries({ queryKey: [...] })` after a successful mutation to keep the UI in sync.
- **Every failure has an addressee.** `useAppMutation` (`src/lib/api/mutationFactory.ts`) reports a failed
  `mutate()` as a toast — the API's message when it sends one, `errorFallback` when it does not. It steps
  aside only where the error already has somewhere to go: an `onError` on the call or on the hook, a
  `mutateAsync` whose awaiter catches and says something, or an explicit `silentError: true`. Never rely
  on omitting a parameter to keep a screen quiet. A bare `await m.mutateAsync(v)` in a click handler is
  not one of those: nothing catches it, so the refusal is lost — `npm run check:mutate-async` refuses a
  new one (it accepts a `try/catch`, `.catch`, `runWithToast`, and a component that shows the reason
  itself, such as `ConfirmDialog`'s `onConfirm`).

### 4. Code Quality & Formatting
- **Tailwind:** Use `cn(...)` utility (from `src/lib/utils.ts`) for conditional classes.
- **Lucide Icons:** sizes per context (16 in buttons, and the rest) come from `UI_GUIDELINES.md` §6 "Icon Guidelines"; don't pick one here. Default `strokeWidth` is `2`.
- **Translations:** NEVER hardcode Polish or English strings in `.tsx` files. Use `i18n` keys.
- **TypeScript 7 compiles, the API stays on 6.** TS 7 ships no programmatic API, and the tools
  that still need one — `typescript-eslint`, knip, and the two scripts that read source with the
  compiler API (`lint-i18n-raw.mjs`, `check-on-error-refusals.mjs`) — check the major version. So
  `npx tsc` is the native compiler via the `@typescript/native` alias, while `typescript` itself is
  aliased to `@typescript/typescript6`: that is the API those tools import, and the version an
  editor resolves. `openapi-typescript`'s `^5.x` peer predates TS 6, so that one peer is pinned to
  the same alias under `overrides`; both aliases and the override collapse back into one
  `typescript` when TS 7.1 ships an API.
- **5-language support:** All modules MUST provide translations in the 5 maintained languages: **en, pl, de, fr, es**. The community `pt` catalogue (`LANGUAGES` in `src/i18n/languages.ts`) may lag; a key it lacks reads English. Every new or updated `i18n` key in `en.json` MUST be accompanied by corresponding entries in `pl.json`, `de.json`, `fr.json`, and `es.json`. Do not ship partial translations.
- **Module display names:** the user-visible name of a module lives in `frontend/src/i18n/locales/*/modules.json` under `modules.<technical_name>.name` (single source of truth; manifest `display_name` is only a fallback for community modules). The approved cross-language name table and the naming glossary are in `docs/MODULE_NAMES.md` — change names there first, not in code.
- **Workspace mode names:** the user-visible name and description of a product profile live in `frontend/src/i18n/locales/*/common.json` under `profiles.<profile_id>.name` / `.description` (single source of truth). Components resolve them through `useProfileLabels`, never by reading `profile.name`. The approved cross-language table lives in `docs/MODULE_NAMES.md` § "Workspace mode names".

### 5. Import Conventions
- **Always use `@/` alias** for all imports. Never use relative `../../` paths beyond one directory.
- **Import order** (a convention — no formatter or lint rule enforces it): React → external libs → `@/components/ui` / `@/lib` → `@/modules` → relative (same module).

### 6. Timers Must Be Owned
- **`setTimeout`/`setInterval` live inside a `useEffect`/`useLayoutEffect`, or they are owned**: the id
  held in a ref, re-arms clear the previous timer, and an unmount effect clears whatever is pending.
  The local ESLint rule `local-rules/timers-in-effects` default-denies every timer outside an effect;
  a file where timers are genuinely owned goes into `frontend/scripts/timer-exceptions.json` with a
  reason that names the owner.
- **Exceptions are counted per site.** An entry declares `sites` — the exact number of unowned timer
  sites its reason covers — and the rule flags every site beyond that number, so adding a new unowned
  timer to a listed file still turns the gate red.
- **"It only touches the DOM" is not a safety reason.** The failure this rule exists for is a timer
  firing after a test-environment teardown — and after teardown `document` disappears exactly like
  `window`, so a DOM-only callback dies there just as hard. Name the owner, or move the timer into an
  effect.

---

### 7. Entry vector: where would a module plug in?

A change to the shared shell (`frontend/src/components`, `frontend/src/lib`, `frontend/src/store`, a Core
page) is finished only when its description answers: *where would a module from outside change or extend
this screen?* Exactly one answer is admissible: **here** — the slot, hook or override is in the same diff,
with a test in which a module registers into it (existing ones are listed in `docs/FRONTEND_MODULE_GUIDE.md`
and, with the backend vectors, in `docs/subsystems/CONTRACTS_STABILITY.md`, "Entry vectors"); **nowhere, on
purpose** — the screen shows an invariant of Core, such as a stock figure that only the posting path
produces, and the change says so in a sentence; or **not yet** — the seam is wanted but unbuilt, and a
tracked issue or task names the debt. Most changes land on "nowhere"; the rule asks for the decision at
writing time, not at an audit. A change whose description does not answer it is not finished. The backend
counterpart, with worked examples, is `backend/AGENTS.md` §4.

## ⚠️ An i18n key with no `t()` call site is not automatically dead

Keys also travel as data (field definitions, reason lists, backend manifests' `title_key`/`label_key`) and
are translated by a generic renderer. Before deleting a reported orphan, grep the raw key across `src/`
**and** `backend/app/modules/`. After touching a manifest run `npm run check:i18n:sync-backend`, which rewrites
`frontend/scripts/i18n-backend-keys.json`; the gate is `npm run check:i18n` (part of `make check-frontend`),
which fails while that snapshot and the manifests disagree.

---

## ⚠️ Frontend Anti-Patterns (NEVER do these)

If you generate any of these patterns, correct them immediately:

| ❌ Anti-Pattern | ✅ Correct Pattern |
|---|---|
| Unconditional `useModuleHook()` (e.g. `useStatsOverview`) | Guard with `enabledModules.includes('module_name')` first |
| `<h1>`, own page header, or ad-hoc `<ArrowLeft>` back link in a module page | Use `useModulePageHeader()` (with `backTo`) — the shell renders title, actions, and back arrow |
| `<PageContainer>` in a module page | Remove — shell handles padding, just return `<div className="space-y-6">` |
| Raw `<input>`/`<select>` for search/filter, `<Tabs>`+`<Input>` combos, or custom per-page filter bars | Use `<ListControlBar>` (`search`, `primaryTabs`, `secondaryFilters`, `filterButton`) |
