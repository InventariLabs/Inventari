# Inventari — Frontend UI Guidelines

> **This file is the single source of truth for all frontend styling decisions.**
> AI agents and developers MUST follow these rules when creating or modifying UI components.

---

## 0. Read this first

Read this section for any UI change, then the sections below for what your change touches.
The rest of the file is reference: you do not need it end to end.

1. **Use the component, never hand-rolled markup** — §2.1 lists them, §12 maps "I need to…" to
   one, §13 lists the helpers (`<Sheet>`, `<StatusBadge>`, `<EmptyState>`, `<QueryResult>`,
   `runWithToast`).
2. **`className` is appearance, never geometry the component already declares** — a width, a
   height or a margin it states is changed through a variant or `wrapperClassName` (§2.0).
3. **Colour by meaning**: `success-*` for "it worked", `accent-*` only for profile-tinted emphasis,
   `text-on-*` for text on a tint (§1.1).
4. **Type**: the scale is 10/12/14/16/18/20, `font-semibold` for titles only (§1.2).
5. **A page inside `ModuleShell`** hands its header to `useModulePageHeader()` and returns
   `<div className="space-y-6">` — no `<h1>`, no `<PageContainer>` (§2.6, §11); a list page starts
   with `<ListControlBar>` (§2.7).
6. **A modal or sheet is `<Sheet>`** with `SheetHeader`, `SheetBody`, `SheetFooter` + `SheetActions`
   (§4.3); one Escape closes one layer.
7. **Every user-visible string** is an i18n key in the five maintained languages — en, pl, de, fr,
   es — (`frontend/AGENTS.md` §4); the community `pt` catalogue may lag and reads English meanwhile.
8. **A settings page** has one save model, named sections with navigation, and its links to other screens
   set apart from the fields (§11.9).

**What the gates already catch.** These run in `make check-frontend` (and `npm run lint:ui` /
`npm run scan:ui`), and each prints the rule it enforces; the sections below give the why only where
the message does not: sizes off the type scale (`check-type-scale`),
`border-2`, a `<select>` without `appearance-none`, a mis-sized `ChevronDown` in `components/ui/`, geometry over
`size="icon"`, a filled destructive button in a row (§2.10, §2.13a — `lint:ui`), a label without a
field, a destructive action in a neutral variant, a hover-only reveal (`lint:ui`), a `<Sheet>`
without a scroll layer, a footer with widths on its buttons or two action rows (§4.3 — `lint:ui`),
a page `<EmptyState>` without a description (`check:empty-state`), `...` in a catalogue string
(`check-i18n-keys`). A native `input[type=date]` (§2.8) is caught by no gate — review is the only
check. `npm run scan:ui` reports every detector, blocking or not, and never fails.

---

## 1. Design Tokens

### 1.1 Color Palette (named in `tailwind.config.js`, valued in `src/index.css`)

| Token        | Tailwind prefix | Main shade | Usage                                                                |
| ------------ | --------------- | ---------- | -------------------------------------------------------------------- |
| **Primary**  | `primary-*`     | `600`      | Brand actions, links, focus rings                                    |
| **Accent**   | `accent-*`      | `500`      | Profile identity / positive emphasis (repainted per product profile) |
| **Success**  | `success-*`     | `500/600`  | Semantic "it worked": confirmations, completed/available statuses    |
| **Danger**   | `red-*`         | `500/600`  | Delete, errors                                                       |
| **Warning**  | `amber-*`       | `500/600`  | Warnings, expiring items                                             |
| **Info**     | `blue-*`        | `500/600`  | Informational, neutral modals                                        |
| **Neutrals** | `gray-*`        | Zinc-based | Text, borders, backgrounds                                           |
| **Freezer**  | `freezer`       | `blue`     | Freezer storage type                                                 |
| **Fridge**   | `fridge`        | `sky`      | Fridge storage type                                                  |
| **Pantry**   | `pantry`        | `amber`    | Pantry storage type                                                  |

#### ⛔ RULE: Use `success-*` for success semantics — NEVER raw `emerald-*`, and not `accent-*`

Product profiles repaint `accent-*` (and `primary-*`) with the profile's identity colour
(ADR-013), so `accent-*` is **not** guaranteed green and must not carry the "it worked" signal.
The `success` token maps to emerald values for every profile. Use `success-*` for success
buttons, badges, and completion feedback; keep `accent-*` only for profile-tinted positive
emphasis that is not a status signal (progress bars, highlighted values).
The only exception is where `emerald` is needed for non-semantic decorative purposes (e.g., checkbox accent color where Tailwind requires a standard color name).

#### Common color combos

| Context            | Classes                                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Primary button     | `<Button>` (default) — `bg-primary-700 hover:bg-primary-800 active:bg-primary-900 text-white`, `dark:bg-primary-800` |
| Success button     | `<Button variant="success">` — `bg-success-800 hover:bg-success-900 active:bg-success-900 text-white`                |
| Danger button      | `<Button variant="destructive">` — `bg-red-600 hover:bg-red-700 active:bg-red-800 text-white`                        |
| Success badge/pill | `bg-success-100 text-on-success` (no border)                                                                         |
| Danger badge/pill  | `bg-red-100 text-on-danger` (no border)                                                                              |
| Warning badge/pill | `bg-amber-100 text-on-warning` (no border)                                                                           |
| Info badge/pill    | `bg-blue-100 text-on-info` (no border)                                                                               |
| Ghost hover        | `hover:bg-surface-raised active:bg-surface-raised` (`<Button variant="ghost">`)                                      |
| Selected/active    | `bg-primary-50 border-primary-500 text-on font-semibold`                                                             |

A filled button is the `<Button>` variant, never these classes by hand: the steps are where white
labels clear WCAG AA in both themes, and `Button.tsx` says why each one sits where it does.
The success button marks the chosen member of a set; it is never a call to action (§2.2).

#### ⛔ RULE: Coloured text on a coloured tint uses `text-on-*` — never a ramp step

The status tints flip to **dark tints** under `.dark` — `success-50…400`, and `red-`, `amber-`,
`blue-` `50…200` (their higher steps are plain Tailwind colours that do not flip) — because they carry
backgrounds. A component that also reads a step from that range for its text gets a
dark-on-dark pair in dark mode: `bg-success-50 text-success-400` measured **1.9:1** — the
APPROVED badge was effectively invisible.

- Pair the status tint — `bg-<status>-100` for a badge, `bg-<status>-50` for a larger fill
  such as a callout — with **`text-on-success` / `text-on-danger` / `text-on-warning` /
  `text-on-info`**. Those four tokens are the text half of the pair and flip with the theme,
  so the component needs **no `dark:` override**, and no border either (§2.12).
- `src/components/ui/__tests__/statusTokenContrast.test.ts` computes the ratios from the
  token values in `index.css` and fails below 4.5:1 in either theme.

#### ⛔ RULE: An active/selected state tints the background — the label stays on `text-on`

Brand-coloured text on a brand-coloured tint cannot be made safe centrally: product profiles
repaint the whole `primary-*` ramp with their own hue (ADR-013), so the pair's contrast
depends on data the shell does not control. The active filter chip measured **1.55:1** this way.

Carry the state with `bg-primary-50` + `border-primary-500` + `font-semibold` and leave the
label on the neutral `text-on`, which is high-contrast in both themes by construction.

### 1.2 Typography

**Font family**: Plus Jakarta Sans (configured in tailwind.config.js)

| Role                   | Classes                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| Page title             | `text-lg md:text-xl font-semibold text-on tracking-tight`            |
| Card title             | `text-lg font-semibold text-on tracking-tight`                       |
| Section title          | `text-base font-semibold text-on`                                    |
| **Record name**        | `text-sm font-semibold text-on`                                      |
| Body text              | `text-sm text-on-secondary`                                          |
| Secondary/hint text    | `text-sm text-on-secondary font-medium`                              |
| Muted/disabled text    | `text-on-muted`                                                      |
| Form label             | `text-xs font-medium uppercase text-on-secondary tracking-wide ml-1` |
| Micro label (metadata) | `text-[10px] font-medium uppercase tracking-widest text-on-muted`    |
| Navigation label       | `text-[10px] font-medium uppercase tracking-widest`                  |
| Code/mono              | `font-mono text-[10px] font-bold tracking-tighter`                   |

#### ⛔ RULE: each weight has one job

Weight stopped carrying information once `font-semibold` covered twelve sizes
from 7px to 24px — 613 call sites, 45% of every weight declaration, the page
title and a 10px caption alike. With one weight spanning the range, hierarchy
rested on size and colour alone and the product read as flat.

| Weight              | Its one job                                                                                           |
| ------------------- | ----------------------------------------------------------------------------------------------------- |
| `font-semibold` 600 | **Titles only**: page (20), card (18), section (16), **record name (14)** — and the selected state (§1.1). |
| `font-medium` 500   | Labels: form label, column header, micro-label, status pill.                                          |
| (none) 400          | Content and data. Digits get `tabular-nums`, not weight.                                              |
| `font-bold` 700     | **Retired**, except a monospace code — there weight is the only thing separating a serial from prose. |

- **Nothing below `text-sm` may carry `font-semibold`.** A micro-label is the
  smaller and lesser of the two label roles; giving it the heavier weight —
  as this table used to — inverts the pair it belongs to.
- **A monospace code is exempt from both weight rules.** On a serial, SKU or
  label, weight is the only thing separating the code from prose, so
  `font-mono` lines follow the Code/mono token above and the type-scale gate
  skips them. The exemption covers _codes_, not data: quantities, prices and
  totals set in `font-mono` are still data and obey the table.
- **Digits get `tabular-nums`, not weight — with one step of emphasis.** Data
  sits at 400; the row's _primary_ figure (the quantity in a stock row, the
  gross in a register row) may step up to `font-medium`. In dense tables
  secondary figures render `text-xs`, the primary figure `text-sm` — size
  ranks within the role, weight never leaves it.
- Size ranks _within_ a role; weight names _which_ role. Both axes only work
  while each says one thing.
- **Every table cell declares its own size; an inherited 16 px is out of
  scale.** No size class means the root's step — one above the sizes a table
  is meant to use — and the type-scale gate is line-scoped: it sees declared
  sizes and weights, never what a cell inherits. Name the step on the cell,
  or once on the row where the children agree, the way the products list sets
  the column-header classes on its `<tr>` and carries them down.

#### ⛔ RULE: uppercase is a label role, a column header or a status, nothing else

The label roles are the three uppercase rows of the table above — form label, micro label,
navigation label. Content is never uppercase.

Counted as visible runs of uppercase on one screen: `maker` 51, `recipes` 47,
`inventory` 6 — one product, an eightfold spread. Uppercase means "this is a
label, not content", and the signal dies when fifty things are labels, while
the costs stay: no word shape to read by, Polish diacritics losing definition
at 10px, and truncation eating whole words (`PCS.` → `PC…`).

- `<Badge>` is sentence case. `<StatusBadge>` adds the uppercase back.
- Counters, meta, chips, buttons and section captions are sentence case.

#### ⛔ RULE: the type scale is 10 / 12 / 14 / 16 / 18 / 20

`text-[10px]` is the only bracketed size in the product; everything else is a
Tailwind step. 7, 8, 9, 11 and 13px are not sizes — `frontend/scripts/check-type-scale.mjs`
fails the build on a new one.

**Text token values** (WCAG AA ≥4.5:1 for sub-18px text on `surface-bg`/`surface-card`):

| Token              | Light    | Dark     | Contrast (card, light/dark) |
| ------------------ | -------- | -------- | --------------------------- |
| `--text-primary`   | zinc-900 | zinc-50  | 17.7:1 / 14.3:1             |
| `--text-secondary` | zinc-600 | zinc-300 | 7.7:1 / 10.1:1              |
| `--text-muted`     | zinc-500 | zinc-400 | 4.8:1 / 5.8:1               |

**⛔ RULE: `text-on-muted` never sits directly on `surface-raised` / `surface-inset`**
Muted text measures 4.4:1 (light) / 4.1:1 (dark) on `surface-raised` and 3.8:1 (light) on
`surface-inset` — below AA for small text.
Use `text-on-secondary` there instead (≥6.1:1 in both modes). Icons on those surfaces may
stay muted (non-text contrast needs only 3:1).

#### ⛔ RULE: Form labels always use `font-medium` — NEVER `font-bold`

`Input`, `Select`, `Textarea` and `DateInput` share one label: the Form label row above. A
custom field (`DynamicFieldsCard`, any other) matches it rather than writing its own.

### 1.3 Spacing Scale

| Use case           | Standard values                            |
| ------------------ | ------------------------------------------ |
| Inline gaps        | `gap-1.5` (xs), `gap-2` (sm), `gap-3` (md) |
| Section gaps       | `gap-4` (lg), `gap-6` (xl)                 |
| Card padding       | `p-6`                                      |
| Modal padding      | `p-5` header, `px-4 pt-3 sm:px-5` footer (`SheetHeader`/`SheetFooter`); `p-5` body, by the caller (`SheetBody` sets none) |
| Page container     | `p-3 lg:p-4 2xl:p-6 3xl:p-8`               |
| Form section space | `space-y-4` or `space-y-5`                 |
| Form field space   | `space-y-1.5` (label-to-input)             |
| Section divider    | `border-t border-border mt-4 pt-4`         |

A divider separates **sections of a form**. A list card is not a form: its
header and its action row are already told apart by spacing and by the
contrast of the buttons, so a rule across the middle only adds a line to
look at. Card footers carry `pt-3` and no border.

### 1.4 Border Radius

| Component              | Radius           |
| ---------------------- | ---------------- |
| Button (sm/md)         | `rounded-lg`     |
| Button (lg)            | `rounded-xl`     |
| Card                   | `rounded-xl`     |
| Form control (all)     | `rounded-lg`     |
| Badge                  | `rounded-lg`     |
| Modal (desktop)        | `rounded-2xl`    |
| Bottom sheet (mobile)  | `rounded-t-3xl`  |
| Bottom sheet (desktop) | `sm:rounded-2xl` |
| Confirm dialog         | `rounded-2xl`    |

### 1.5 Shadows

| Context        | Class              |
| -------------- | ------------------ |
| Card default   | none (border only) |
| Card elevated  | `shadow-md`        |
| Card hover     | `hover:shadow-lg`  |
| Button primary | `shadow-sm`        |
| Modal          | `shadow-xl`        |
| Dropdown menu  | `shadow-2xl`       |
| Select listbox, date popover | `shadow-lg` |

---

## 2. Component API Reference

### 2.0 Who owns which class

The rest of this document says what things should look like. This section says
**who gets to say it** — the component, or the call site — because most of the
visual bugs a review keeps missing are neither party being wrong about the look.
They are the call site restating geometry the component had already declared,
in a way that only half works.

| Layer                         | Owner     | Declared as                                       |
| ----------------------------- | --------- | ------------------------------------------------- |
| Height of a control           | component | `size` on `<Button>`, the base classes on a field |
| Width of a field's box        | call site | `wrapperClassName`                                |
| Width of a footer's buttons   | component | `<SheetActions>`                                  |
| Overflow of a horizontal row  | component | `<ScrollRow>`, `<TabsList>`                       |
| Colour, type, padding, radius | call site | `className`                                       |

So: **`className` describes appearance, never geometry the component has already
declared.** A width, a height, a margin or a share of a flex row that the
component states is not yours to restate from outside — either the component
offers a variant for what you need, or it needs one adding.

#### Why an override is not simply an override

`cn()` is `twMerge`, and twMerge resolves conflicts **within a variant group**.
A class with no responsive modifier does not displace the same class with one:

```tsx
// size="sm" is `h-11 … md:h-8`
<Button size="sm" className="h-auto">   // ⛔
```

`h-auto` beats `h-11` and leaves `md:h-8` standing. The button obeys below `md`
and ignores you on every desktop. Nothing errors, nothing looks wrong in the
diff, and a unit test asserting the className passes — which is why this exact
shape shipped three times before a rule caught it.

The same asymmetry is why a class moved to the wrapper is not the same class.
`w-auto` on a `<select>` is the width of the chosen option; on the `<div>` around
it, `width: auto` is the whole row. Use `w-fit` when you meant "as wide as its
content", and `focus-within:` where you had `focus:` — a box never takes focus
itself.

#### What to do instead

- **A size you need does not exist** → add it to the variant, free of responsive
  modifiers so it cannot be half-overridden. `iconSm`, `inline`, `row`, `content`
  and `contentSm` on `<Button>` all exist for exactly this reason.
- **The box, not the control** → `wrapperClassName`. Every field component
  (`Input`, `Textarea`, `Select`, `NativeSelect`, `DateInput`, `SearchableCombobox`) renders its box
  every time, labelled or not, so the prop always lands.
- **A row of actions** → `<SheetFooter>` + `<SheetActions>` (§4.3), which state
  both halves of the phone/desktop width rule so no call site has to.
- **A field label** → the control's `label` prop. A hand-rolled `<label>` is
  inline by default, so it sits in a line box the wrapper's inherited
  line-height sizes — about 8px taller than the text — and the field under it
  lands that much lower than the `DateInput` beside it in the same grid row.
  Where the control has no `label` prop, the label needs `block` of its own.

Each of these has a rule behind it — `npm run lint:ui` fails `make check-frontend`
when one breaks (the commit hook does not run it), and `npm run scan:ui` prints every pattern the detectors know
about, blocking or not, so two runs can be compared while a class is being
drained. The detectors live in `frontend/scripts/ui-patterns/`, one file per
class of mistake, each carrying the sentence it prints when it finds one.

### 2.1 Mandatory Components — ALWAYS use these

> **⛔ NEVER write inline button/card/input/badge styles. Use the component from `src/components/ui/`.**

| Component              | Import from                        | When to use                     |
| ---------------------- | ---------------------------------- | ------------------------------- |
| `<Button>`             | `components/ui/Button`             | ALL clickable actions           |
| `<Card>` family        | `components/ui/Card`               | ALL content containers          |
| `<Input>`              | `components/ui/Input`              | ALL text inputs                 |
| `<Select>`             | `components/ui/Select`             | Icon and colour pickers         |
| `<NativeSelect>`       | `components/ui/NativeSelect`       | Option-based selects            |
| `<SearchableCombobox>` | `components/ui/SearchableCombobox` | Searchable dropdowns            |
| `<Badge>`              | `components/ui/Badge`              | Status labels, tags             |
| `<ConfirmDialog>`      | `components/ui/ConfirmDialog`      | Destructive action confirmation |
| `<Checkbox>`           | `components/ui/Checkbox`           | Every on/off setting (§5.4)     |
| `<DynamicIcon>`        | `components/ui/DynamicIcon`        | Icons by name string            |
| `<DateInput>`          | `components/ui/DateInput`          | ALL date fields (§2.8)          |
| `<Tabs>` family        | `components/ui/Tabs`               | ALL tab navigation (§2.5)       |
| `<ListControlBar>`     | `components/ui/ListControlBar`     | Controls of a list page (§2.7)  |

### 2.2 Button variants

```tsx
// Primary action (main CTA)
<Button variant="primary">Save</Button>

// Secondary action
<Button variant="secondary">Cancel</Button>

// Outline (less emphasis)
<Button variant="outline">Filter</Button>

// Ghost (minimal)
<Button variant="ghost" size="icon" aria-label={t("common:a11y.close")}><X size={18} /></Button>

// Danger, filled — the confirmation dialog's own action only (§2.13a); `destructive` is the same
<Button variant="danger">Delete</Button>

// Danger in a row — the label carries the warning at rest (§2.13a)
<Button variant="ghostDanger">Deactivate</Button>

// No variant renders `default`, the same as `primary`; `link` is an underlined text action
<Button variant="link">Learn more</Button>

// Success (marks the chosen member of a set — a state, never an action; see below)
<Button variant="success" aria-pressed>Chosen</Button>

// Sizes: sm (h-11, md:h-8), md (h-11, md:h-10, default), lg (h-12),
//        icon (h-11 w-11, md:h-10 w-10), iconSm (h-8 w-8), inline (intrinsic),
//        row (full width, height from content), content / contentSm (height from content)
<Button size="sm">Small</Button>

// Loading state
<Button isLoading>Saving…</Button>

// With icons
<Button leftIcon={<Plus size={16} />}>Add item</Button>
```

**`success` reports a state; it never asks for an action.** The variant is a
status colour — "this is on", "this member of the set is chosen" — and it sits
one ramp step from `primary` (`success-800` against `primary-700`), which in the default profile is green as well. A screen that
used it as a call to action put two almost identical greens in one column:
`Consume 1` in `primary` beside `Add to shopping list` in `success`, two actions
of entirely different consequence reading as the same weight, with the shade
difference looking like a rendering artefact rather than a distinction. A button
that _does_ something is `primary` (the one main action), or `outline` / `ghost`
by weight. Where several buttons form a set and one of them is chosen, `success`
may mark the chosen one.

**Never shrink an icon button with a class — pick the smaller size.** `icon` keepsa 44px touch target below `md:` and drops to 40px above it, and that `md:` prefix
is exactly what makes `className="h-8 w-8"` fail: `cn()` is `twMerge`, which does
not drop a class carrying a responsive modifier for an override that has none.
The override wins on phones and loses on every desktop, so the button _looks_
resized in the code and renders 40px in the browser. Use `iconSm` for a compact
control in a row or an action bar, and `inline` for something that reads as an
icon inside content — a colour swatch, a star on a tile — where the size comes
from the element itself. `inline` sits below the 44px touch floor deliberately,
so use it only next to a larger target or on a surface that is clickable as a
whole. `npm run lint:ui` fails the build on a geometry class over `size="icon"`.

### 2.3 Card compound components

```tsx
<Card>
  {" "}
  {/* or variant="elevated" | "ghost" */}
  <CardHeader>
    <CardTitle>Title</CardTitle>
    <CardDescription>Subtitle</CardDescription>
  </CardHeader>
  <CardContent>{/* main content */}</CardContent>
  <CardFooter>
    <Button variant="primary">Save</Button>
  </CardFooter>
</Card>
```

### 2.3a The clickable card

A card that navigates should navigate from anywhere on it — that part is not in
question. What matters is what does the navigating, and there are exactly two
shapes.

**No actions inside the card** → wrap the card in the link.

```tsx
<Link to="/inventory/items">
  <Card hoverable className="p-5">
    …
  </Card>
</Link>
```

**The card has its own buttons** (edit, delete, a status action) → a real link
on the title, stretched over the card by a pseudo-element. Buttons never nest
inside an `<a>`; that is invalid HTML and browsers repair it in ways nobody
designed.

```tsx
<Card hoverable className="group relative …">
  <h3>
    <Link
      to={`/lists/${list.id}`}
      className="after:absolute after:inset-0 focus-visible:outline-none focus-visible:ring-2 …"
    >
      {list.name}
    </Link>
  </h3>
  …
  <div className="relative z-10">
    <Button …>Edit</Button>
  </div>
</Card>
```

**Never `<div onClick>`.** It takes no focus, has no role, is not announced,
and cannot be reached from a keyboard. Three cards did it before this rule and
each was unusable without a mouse.

`hoverable` raises the shadow and nothing more. The pointing cursor comes from
the link — the element that actually goes somewhere — so a card with no
destination cannot look like it has one.

What the pattern costs, and where it does not apply:

- The overlay sits above the card's text, so selecting that text with the mouse
  is no longer possible. Acceptable for a card of labels; not for one holding a
  paragraph a reader would want to copy.
- A second link to the same place inside the card (a "Open" button, say) is a
  duplicate for a screen reader. Hide it with `tabIndex={-1}` and
  `aria-hidden="true"` — or drop it, since the whole card is the link now.
- **One destination only.** A card with two equally important places to go
  keeps no stretched link at all; the reader picks from the links themselves.

### 2.4 Badge variants

```tsx
<Badge variant="success">Active</Badge>    // green
<Badge variant="danger">Expired</Badge>     // red
<Badge variant="warning">Expiring</Badge>   // amber
<Badge variant="info">Frozen</Badge>        // blue
<Badge variant="secondary">Draft</Badge>    // gray
<Badge variant="outline">Custom</Badge>     // border only
<Badge>Default</Badge>                       // primary brand
```

---

### 2.5 Tabs component

Use `<Tabs>`, `<TabsList>`, `<TabsTrigger>`, `<TabsContent>` from `@/components/ui/Tabs` for **all tab navigation**. Never hand-roll tab buttons.

```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";

// Uncontrolled (simplest)
<Tabs defaultValue="info">
  <TabsList>
    <TabsTrigger value="info" icon={<Info size={16} />}>
      Info
    </TabsTrigger>
    <TabsTrigger value="history">History</TabsTrigger>
  </TabsList>
  <TabsContent value="info">
    <InfoPanel />
  </TabsContent>
  <TabsContent value="history">
    <HistoryPanel />
  </TabsContent>
</Tabs>;

// Controlled (when external state is needed)
const [tab, setTab] = useState<"info" | "history">("info");
<Tabs
  defaultValue="info"
  value={tab}
  onValueChange={(v) => setTab(v as "info" | "history")}
>
  ...
</Tabs>;
```

**Rules:**

- `defaultValue` is always required, even in controlled mode.
- Do NOT mix `TabsContent` with manual `{activeTab === "x" && ...}` — pick one pattern per component.
- `TabsList` is `inline-flex` by default (sizes to content). Pass `className="w-full"` to force full width on mobile/desktop.
- Always use `icon` prop on `TabsTrigger` instead of embedding the icon in `children`.

---

### 2.6 Module Page Headers

Both `ModuleShell` and `SettingsShell` render the page header (title + subtitle + actions slot) via `PageHeaderContext`. Pages **must not** render their own `<h1>` when inside either shell — use the `useModulePageHeader()` hook instead.

An ESLint rule (`no-restricted-syntax`, an error) forbids `<h1>` in `src/modules/**/*.tsx`; the few
files that own a heading of their own are named in its `ignores` in `eslint.config.js`.

```tsx
import { useModulePageHeader } from "@/hooks/useModulePageHeader";

export default function MyModulePage() {
  const { t } = useTranslation("myModule");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      title: t("pageTitle"),
      subtitle: t("pageSubtitle"),
      actions: (
        <Button leftIcon={<Plus size={16} />} onClick={() => setOpen(true)}>
          {t("addButton")}
        </Button>
      ),
    });
  }, [t, setHeader]);

  // Return content only — no <h1>, no <PageContainer>
  return <div className="space-y-6">{/* ... */}</div>;
}
```

**Rules:**

- Works in **both** `ModuleShell` pages (e.g. Items, Recipes) and `SettingsShell` pages (e.g. General, Webhooks, Access & Roles).
- `useEffect` registering `setHeader` **must** be placed before any early returns (`if (isLoading) return ...`).
- **No manual cleanup needed.** `useModulePageHeader()` resets the header to empty automatically when the page unmounts — do NOT add `return () => setHeader({})` in your own effect.
- **Detail pages** (e.g. `RecipeDetailPage`, `AssetDetailPage`) with custom hero layouts and back navigation keep their own inline header markup; one that renders an `<h1>` is in the rule's `ignores`
  (`StorageDetailHeader`, `StockTakeHeader`), since the rule is an error, not a warning.

---

### 2.7 ListControlBar — unified search/filter bar

Every list page MUST use `<ListControlBar>` instead of building ad-hoc search inputs or tab bars. This ensures consistent layout, spacing, and accessibility across all modules.

```tsx
import { ListControlBar } from "@/components/ui/ListControlBar";

// Minimal — search only
<ListControlBar
  search={{ value: search, onChange: setSearch, placeholder: t("searchPlaceholder") }}
/>

// Full — search + tabs + secondary filter chips + view toggle
<ListControlBar
  search={{ value: search, onChange: setSearch, placeholder: t("searchPlaceholder") }}
  primaryTabs={{
    value: activeTab,
    onChange: (v) => setActiveTab(v as TabType),
    options: TABS.map((tab) => ({ value: tab.value, label: t(tab.labelKey) })),
  }}
  secondaryFilters={[
    { key: "expiring", label: t("onlyExpiring"), active: expiringFilter, onToggle: () => setExpiringFilter((p) => !p) },
  ]}
  viewToggle={{ mode: viewMode, onChange: setViewMode }}
  filterButton={{ activeCount: activeFilterCount, onClick: () => setShowFilters((p) => !p) }}
  resultCount={filteredItems.length}
/>
```

**Props:**

| Prop                    | Type                                     | Description                                                                       |
| ----------------------- | ---------------------------------------- | --------------------------------------------------------------------------------- |
| `search`                | `{ value, onChange, placeholder? }`      | Renders a search input with clear button                                          |
| `primaryTabs`           | `{ value, onChange, options[], label? }` | Renders `<Tabs>` inline with search; `label` names what the row filters by        |
| `secondaryFilters`      | `{ key, label, active, onToggle }[]`     | Chip toggles on row 2                                                             |
| `secondaryFiltersLabel` | `string`                                 | What the chip row filters by — two unlabelled rows read as one filter             |
| `primaryAction`         | `ReactNode`                              | The page's actions ("Add", "Import"…) at the end of row 1; a fragment for several |
| `viewToggle`            | `{ mode, onChange }`                     | Grid/List toggle buttons                                                          |
| `filterButton`          | `{ activeCount, onClick }`               | Filter tray trigger with badge                                                    |
| `resultCount`           | `number`                                 | Shows "N results" when set                                                        |
| `resultCountLabel`      | `string`                                 | Custom noun after the count (default: the translated "N results")                 |
| `resultCountCapped`     | `boolean`                                | The list stopped counting at `resultCount`: reads "more than N"                   |
| `className`             | `string`                                 | Extra classes on the outer wrapper (spacing in the page layout)                   |

**Rules:**

- Place `<ListControlBar>` as the **first element** inside the page's `<div className="space-y-6">`.
- Pass no props when there are truly no controls — the component returns `null` for consistent vertical spacing.
- An ESLint rule forbids a raw `<select>`, and a raw `<input>` with no `type` or `type="text"`, in `src/modules/**/pages/*.tsx`.
- Use `primaryTabs` for **mutually exclusive** status/type filters; use `secondaryFilters` chips for **independent** boolean toggles.

---

### 2.8 DateInput — the only date field

Every date field MUST use `<DateInput>`. A native `input[type=date]` formats
itself from the _browser's_ locale while the rest of the UI formats from the
_app's_, so the same date read one way in a list and another in the form that
edits it; it also cannot be styled for dark mode.

```tsx
import { DateInput } from "@/components/ui/DateInput";

<DateInput
  label={t("fields.expiryDate")}
  value={expiryDate} // "yyyy-MM-dd" or ""
  onChange={setExpiryDate} // receives the string, not an event
  presets={["plus1Week", "plus1Month", "plus6Months"]}
  min={today} // optional range
/>;
```

- **Presets belong to the field, not the component.** A shelf-life date thinks
  in intervals ("in a month"); a purchase date thinks backwards. System fields
  declare theirs via `date_presets` in `src/config/systemFields.ts`. The
  component's own default is an empty list — a field with no case for shortcuts
  renders no bar above the calendar.
- **A shortcut earns its place only if it saves navigation or names the usual
  value.** The panel opens on a six-week grid around the field's value, or around
  today when it is empty, so "Today", "Yesterday" and "A week ago" are already one click away: a button for them
  costs the same click, takes a strip above the calendar, and implies those are
  what the field normally holds — nobody puts food in the freezer with last
  week's date. Offer a shortcut when its target lies outside the open grid (six
  months, a year, three years out), or when it is the overwhelmingly common
  value for that field, not merely a plausible one. List filters are a different
  thing: there "last week" names a range, not an event, and this rule does not
  apply.
- **Distance is the header's job, not the bar's.** Month chevrons alone put a
  date three years out 36 clicks away, which is what the shortcut bar kept being
  asked to paper over. The header carries year arrows too, one year a click, so a
  date three years out is three clicks rather than 36.
- **"Today" is local.** Never compute a date through `toISOString()` — between
  midnight and 02:00 local time it answers with yesterday.
- The panel is a popover on desktop and a bottom sheet on phones (§4.3), the
  grid is keyboard-navigable (arrows, PageUp/PageDown, Home/End, Enter,
  Escape), and day cells are 44px tall.

#### ⛔ RULE: Never render `input[type="date"]`

`grep -rn 'type="date"' src --include=*.tsx | grep -v test` must stay empty.

### 2.9 Type scale floor

**10px is the smallest text in the product** (`text-[10px]`, the micro-label
role in §1.2); `check-type-scale.mjs` fails on a smaller one.

- Do not stack `opacity-*` on top of small text to de-emphasise it; use
  `text-on-secondary` / `text-on-muted`, which keep AA contrast.
- Navigation labels are the one documented exception (§1.2) and already sit at
  their own token.

### 2.10 Form control geometry — one scale

Controls that do the same job must **look** like they do the same job. In the
"New document" dialog, as measured, one section held a 40px/8px-radius
select, a second identical select, and a 44px/12px-radius date field directly
below them — plus a border that was 1px on lists and 2px in dialogs.

Every form control — `Input`, `Textarea`, `NativeSelect`, `Select`, `DateInput`,
`SearchableCombobox` — uses one scale:

| Property        | Value                                                        |
| --------------- | ------------------------------------------------------------ |
| Height          | `h-11 md:h-10` (44px touch target, 40px desktop density); `Textarea` is `min-h-24 resize-y` |
| Radius          | `rounded-lg` (8px)                                           |
| Border          | `border border-border` (1px, in every context)               |
| Horizontal pad  | `px-3`; a `<select>` takes `pr-10` for its indicator         |
| Text            | `text-sm`                                                    |
| Label → control | `space-y-1.5` (6px), owned by the control's own wrapper      |
| Label display   | `block` — an inline label inherits the wrapper's line-height |
| Error message   | `text-xs text-red-600 font-medium ml-1`, below the control (`Select` shows it inside its trigger; `DateInput` only reddens its border) |

- **Pass `label` to the control; never hand-roll a `<label>` beside it.** The
  wrapper owns the label-to-field gap — the measured rhythm of 12 / 0 / 19 / 7px
  came from forms spacing their own labels. Every control above accepts `label`.
  It is also the only thing that puts the name in the accessibility tree: a
  `<label>` written above a field with neither `htmlFor` nor the control inside
  it is styled text, and the field is announced without a name. Where the layout
  puts the label _beside_ the field, give the control an `id` and point
  `htmlFor` at it. `npm run lint:ui` fails on `label-without-field`.
- **A group of options is labelled as a group, not with a `<label>`.** A row of
  chips where exactly one is chosen has no single field for a label to point at.
  `ChoiceGroup` (`components/ui/ChoiceGroup.tsx`) names the group through
  `aria-labelledby` (a `radiogroup`) and marks the chosen chip `aria-checked`, so the choice
  is not carried by colour alone.
- **Filled is not a state.** Having a value never recolors the border, the
  background, or the font weight — two filled controls of different kinds must
  read as the same kind of field, and only `error` and `:focus` may tint the
  frame. The placeholder-vs-value distinction is carried by text colour alone
  (`text-on-muted` / `data-[placeholder]` vs `text-on`), exactly like `Input`.
- **Do not raise a border to `border-2` for emphasis.** Emphasis is colour
  (`border-primary-500`) plus a tint, not thickness — a 2px border changes the
  control's outer box and breaks alignment with its neighbours. This holds for
  cards and selection tiles too, not only for form controls: a 2px card wrapping
  a 1px card shows both weights in one tile. `npm run lint:ui` fails on
  `border-2`; the single exception it allows is a _transparent_ one used as
  geometry rather than as a frame, such as the inset a switch knob travels
  within.
- `size="sm"` on `Select` is the one compact variant (`h-9`, `text-xs`); it keeps
  the same radius and border weight.
- **Label geometry is shared, not negotiated per screen.** Every
  control draws its label from one class string; `labelClassName` exists for
  what is _not_ geometry — today, responsive visibility, where a label folds
  away because a column header takes over (`xl:sr-only` in `LineItemsEditor`).
  It is not a way to re-decide size, case, weight, tracking, colour or margins:
  a screen that wants another label voice changes the shared one for everyone
  or leaves a second voice in the app, which is the defect this section exists
  to prevent. Nine call sites once used the prop to undo the canonical geometry
  and were snapped back to it; margins especially belong to the wrapper's
  `space-y-1.5` — a label adding `mb-*` stacks its own gap on top.
- **One disclosure indicator.** Anything that opens a list or expands a section —
  `Select`, `NativeSelect`, a collapsible section header — draws the same
  `ChevronDown` from lucide at `size={18}`, `text-on-muted`, at the trailing
  edge. A `<select>` therefore always carries `appearance-none` and `pr-10`:
  left to the platform it renders whatever arrow the OS and the browser agree
  on, and one storage sheet showed a system arrow, a lucide chevron and a third
  one within a single column. The indicator is ours, the control is not — the
  element stays a native `<select>` so a phone keeps opening the system picker.
- **A section header that reads as a control is a control.** A collapsed
  disclosure box standing in a form column takes the height, radius and padding
  from this table; it may only grow past that height when it genuinely carries a
  second line. `npm run lint:ui` fails on a `<select>` without
  `appearance-none`, and on a `ChevronDown` in `components/ui/` drawn at another
  size or hung off a control that states no height.

### 2.11 Heading levels — never skip one

A screen-reader user navigates a page by its heading outline. Six screens across
the trade modules went `h1` → `h3` with no `h2`, which reads as a missing level.

| Level | Who renders it                                                       |
| ----- | -------------------------------------------------------------------- |
| `h1`  | The shell (`PageHeader`). A module page **never** renders its own.   |
| `h2`  | The first level of content: a card/section title, a list row's name. |
| `h3`  | Only inside a section that already has an `h2`.                      |

- `<CardTitle>` renders `h2` by default. Pass `as="h3"` only for a card nested
  inside a section with its own `h2`.
- A raw `<h3>` directly under the page title is the bug this rule exists for.
  Check with: `document.querySelectorAll('h1,h2,h3,h4')` — the levels must not
  jump by more than one going down the page.

### 2.12 Borders — only where a layer ends

A documents list at 390px carried **109 outlined elements**: one per card, one
per badge inside those cards, one per filter chip, plus every control. Nothing
stood out, because everything was framed.

- **Keep the outline** where one layer ends and another begins: a card on the
  page, a dialog over the page, a form control the user can type into.
- **Inside a card, and inside a filter bar, use a fill or a gap instead.** The
  status badge is `bg-<status>-100` with no border; the filter chip is
  `bg-surface-raised` (inactive) or `bg-primary-50` + `ring-1` (active).
- A container that already has its own background (`bg-surface-inset`) does not
  also need a border.

### 2.13 Horizontal scrollers announce themselves

A row with `overflow-x-auto` and nothing else hides its overflow behind a hard
edge — the status filters ended at "Confirmed" with no sign that "Completed" and
"Cancelled" were one swipe away — while the browser's own scrollbar renders as a
thick grey bar that reads like a UI element.

Use `<ScrollRow>` (`@/components/ui/ScrollRow`) for any horizontally scrolling
row of controls. It hides the scrollbar and fades the content at whichever end
still has content behind it, using a mask so it works on any background.

### 2.13a Destructive actions in a row are separated and coloured

Three modules have now shipped the same row: `Edit | Deactivate`,
`Edit | Confirm | Cancel` — the destructive action flush against the safe one,
in the same weight, with the warning appearing only on hover. On a touch screen
there is no hover, so the first signal arrives after the tap.

- Put a divider (`<span aria-hidden className="w-px h-5 shrink-0 bg-border mx-1" />`)
  between the safe actions and the destructive one. Give it an explicit height —
  `self-stretch` collapses to nothing inside the `items-center` row it sits in.
- Give the destructive action `variant="ghostDanger"` — the label carries the
  colour at rest, not on hover. Reserve the filled `danger`/`destructive`
  variants for the confirmation dialog, where the action is the point of the
  screen; inside a row a filled red button outweighs the row's own content.
- An action that is destructive **in one state only** (deactivate/activate)
  switches variants with the state.
- **Match the divider to the axis it separates.** The rule above assumes a
  horizontal row. Where the actions stack — a full-width action block in a
  card, the row below `sm` — a `w-px` divider is a zero-width element on a
  line of its own, and reads as an unexplained gap. Turn it with the layout:
  `h-px w-full my-1` in a stack, `w-px h-5 mx-1` in a row.
- **In a sheet footer, give it its own row instead of the divider.** The footer
  stacks below `sm` (§4.3), so a delete sitting in the action row lands
  directly under the primary button — a mis-click waiting for a hurried thumb.
  Its own row, aligned to the far end from Save (`sm:justify-start`), keeps the
  separation the divider provides in a horizontal row.

`npm run lint:ui` enforces this on `<Button>`. Some filled red buttons are
right anyway — a screen that expands into its own confirmation step instead of
opening a dialog, a remove chip sitting on a photo where a ghost button
disappears into whatever the user photographed. Those say so at the call site,
in the shape the backend's architecture linter already uses:

```tsx
{
  /* ui-pattern: filled-destructive — the section has already expanded into its
    confirmation step, so this button is the confirm and not the trigger */
}
<Button variant="destructive" onClick={doArchive}>
  Archive
</Button>;
```

The reason has to be a sentence — five words or more, or the gate ignores the
marker. A list of exempt paths with no argument attached is where a rule goes
to be forgotten.

The opposite failure is a destructive action wearing a neutral variant —
`Edit | Delete` with `Delete` in `ghost`, the warning arriving only on hover,
which a touch screen never sends. `npm run lint:ui` fails these under
`destructive-as-neutral`: it cannot read the variant, so it reads the i18n
key, because the label is translated and the key is not. Variants given as an
expression are skipped — the state switch above is a judgement a static read
cannot make. The class is drained and the detector blocks.

### 2.13b Card-row actions hug the right edge in both layouts

The canonical list-card row is `flex flex-col gap-3 sm:flex-row sm:items-center
sm:justify-between`: content left, actions right. From `sm` up the buttons sit
on the card's right edge; below `sm` the row folds into a column and the
buttons, given no alignment of their own, land on the left — hanging mid-card
with an empty band to their right, and the edge they belong to flips side with
the window width.

- Give the actions container `self-end sm:self-auto` — one pair of classes on
  the button container, no change to the content layout. (`items-end` on the
  parent is the wrong tool: it would shrink the text block to its content
  width too.)
- The rule is about **actions**, not whatever stands on the right. A row whose
  right side carries text, an amount or a badge — `ApprovalsDashboard`,
  `ExecutionLineCard`, `DocumentApprovalsPage`, `POLinesCard` — keeps folding
  that content under the left column: it is still content, not a control, and
  pulling it right would fake a second column.

### 2.13c A control hidden by transparency comes back on focus

`opacity-0 group-hover:opacity-100` on a row's actions hides the whole control
from a finger (which never sends a hover) and leaves it focusable at
`opacity: 0` for a keyboard.

- Hide it **only above the hover breakpoint**: `md:opacity-0`. Below it — which
  is to say on a touch screen — the action is simply visible.
- Bring it back on focus: `md:group-focus-within:opacity-100` beside the hover
  class. Both guards, not one: a focus reveal alone still leaves a finger with
  nothing to tap, and a breakpoint alone still hides the control from a
  keyboard on a laptop.
- The canonical spelling, already in `RecipeCard` and `CollectionsPanel`:
  `md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100`.
- A tooltip is not a control — nothing focuses it and nothing taps it — so
  `pointer-events-none` is the marker that exempts it.

`npm run lint:ui` enforces this as `hover-only-reveal`.

### 2.14 Module navigation bar — from two items up

`ModuleShell` renders the module nav bar only when the module has **more than
one** desktop nav item. A tab that selects the module's only page is noise, so a
single-screen module (partners, shopping lists) renders no bar — and that is the
rule, not an oversight to fix.

The shell **reserves the band's height** either way, so a single-screen module's
content starts at the same height as every other module's. Do not add a
placeholder tab to fill it.

### 2.14a A module's settings live in the module, last in its nav

Options that change how a module behaves belong to that module's own nav bar,
as the **final** item (`order: 90` by convention) — never wedged between two
working screens, and never only in the global settings shell.

- The global `/settings` shell groups module-contributed `settingsSections`
  under **Integrations**. An inventory or production module's options are not an
  integration; sections there are for things that talk to the outside world
  (API keys, webhooks). Contributing a section is opt-in, not the default home.
- Reason for "last": the nav bar is read left to right as a workflow, and
  configuration is not a step in it. Maker's settings sat only in the global
  shell; purchase orders and recipes had theirs in the middle of the bar, so the
  eye had to step over configuration to reach the next working screen.

## 3. Layout Patterns

### 3.1 Page structure

```
┌─── APP SHELL (top bar, always visible) ─────────────────────────────────────┐
│  [🏠] [📦][🖥️][👨‍🍳][📊]  · Active Module ·  [⌘K]  🔔  👤              │
├─── MODULE SHELL (module-scoped nav, when module has nav) ───────────────────┤
│  [Dashboard] [Items] [Storages] [Labels] [Scan]          (desktop: h-11 bar) │
├─── MODULE CONTENT ──────────────────────────────────────────────────────────┤
│  Header / Title / Filters (sticky if needed)                                 │
│  Content: grid/list                                                          │
│  Pagination (if applicable)                                                  │
└─────────────────────────────────────────────────────────────────────────────┘

Mobile:
┌──────────────────────────┐
│ 🏠  [📦 Inventory ▾] 🔔 👤│  ← AppShell top bar
├──────────────────────────┤
│ Module Content           │
├──────────────────────────┤
│ Module-scoped bottom nav │  ← MobileModuleNav, rendered by AppShell
└──────────────────────────┘
```

### 3.2 Responsive grid

```tsx
// Standard 2-column form
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">

// Responsive card grid
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
```

### 3.2a Page Container Sizing

> **⛔ RULE: Page width is set exclusively by `<PageContainer>` — NEVER put `max-w-*` (+ `mx-auto`) directly on a page root.**
> A view root either uses `<PageContainer>` (standard or `wide`) or sets no width limit at all.
> `max-w-*` **inside** content (forms, paragraphs, empty-state cards) is intentional and stays.
>
> **Exception — Module pages inside ModuleShell**: Module pages rendered inside `ModuleShell` must NOT use `<PageContainer>`. The shell already provides padding — `AppShell` pads the page, and `ModuleShell` adds the wider desktop gutter from `md:` up (below that it adds nothing, because two 12px layers ate 6% of a 390px phone screen). Return `<div className="space-y-6">` directly from your module page component.

```tsx
import { PageContainer } from '@/components/ui/PageContainer';

// Outside ModuleShell only. Standard (1536px) — forms, lists
<PageContainer className="space-y-6">
  {/* content */}
</PageContainer>

// Outside ModuleShell only. Wide (1920px) — dashboards, data tables, grids
<PageContainer wide className="space-y-6">
  {/* content */}
</PageContainer>
```

| Tier     | Max-width                   | When to use                                              |
| -------- | --------------------------- | -------------------------------------------------------- |
| Standard | `max-w-screen-2xl` (1536px) | A page outside the shells that reads as a column (forms, text, gates) |
| Wide     | `max-w-[1920px]`            | A page outside the shells that needs the full width (the app store)    |

Module pages take 1920px from `ModuleShell` and settings pages from `SettingsShell`, whatever
their content; the tiers are for pages outside both. `<PageContainer>` also sets `pb-32`, so a
page inside it adds no bottom padding of its own.

### 3.2b Grid Scaling Guide (recommended patterns)

```
Cards/tiles:
  grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 3xl:grid-cols-5

Stats cards:
  grid-cols-2 lg:grid-cols-4 3xl:grid-cols-6

Settings panels:
  grid-cols-1 md:grid-cols-2 2xl:grid-cols-3

Page padding:
  p-3 lg:p-4 2xl:p-6 3xl:p-8
```

### 3.3 Breakpoints

| Breakpoint | Width  | Purpose                                             |
| ---------- | ------ | --------------------------------------------------- |
| `xs`       | 475px  | Small phone adjustments                             |
| `sm`       | 640px  | Modal layout shift, padding increase                |
| `md`       | 768px  | **Major shift**: desktop module nav and settings sidebar appear, mobile bottom nav hides; grid 2-column |
| `lg`       | 1024px | Wider page gutter (`lg:p-4`); no navigation change   |
| `xl`       | 1280px | Larger modals, 4-column grids                       |
| `2xl`      | 1536px | Wide desktop: 4–5 columns, larger padding           |
| `3xl`      | 1920px | Ultra-wide / 4K: 5–6 columns, max-width cap         |

### 3.4 Page Container Standard (MANDATORY)

Every new page outside `ModuleShell` MUST use `<PageContainer>` (wraps `max-w-screen-2xl` or `max-w-[1920px]`). `AppShell.tsx` provides `p-3 lg:p-4 2xl:p-6 3xl:p-8` padding — pages must NOT add their own top-level padding.

> **Module pages** (inside `ModuleShell`) are an exception: they must NOT wrap in `<PageContainer>` because the shell already provides sizing and padding. Return `<div className="space-y-6">` directly.

> **Shell height tokens**: AppShell top bar = `h-14` (56px, `top-0`). ModuleShell nav bar = `h-11` (44px, `sticky`, below the top bar and any app notice: `top-[calc(3.5rem+var(--app-notice-height,0px))]`). The mobile bottom nav (`MobileModuleNav`, rendered by AppShell) is `fixed bottom-0` at `--mobile-nav-height` (4rem, 64px). AppShell pads `<main>` by that height on phones, so a page adds no bottom padding for it.

The widths are the two tiers of §3.2a — `<PageContainer>` (1536px) and `<PageContainer wide>`
(1920px) — and `PageContainer` sets them; a page root never writes `max-w-*` itself.

#### Rules

1. **Never add `p-*` or `px-*` padding** — the app shell (`AppShell.tsx`) provides it. Duplicate padding creates inconsistent gutters.
2. **`space-y-6`** for vertical section spacing, the same rhythm as a module page (§10 #17).
3. **Optional entry animation**: `animate-in fade-in slide-in-from-bottom-2 duration-300`.

```tsx
// ❌ BAD — a width on the page root, duplicate padding
<div className="max-w-4xl mx-auto px-4 py-6 space-y-6">

// ✅ GOOD — outside ModuleShell
<PageContainer className="space-y-6">
```

---

## 4. Modal / Sheet Patterns

### 4.1 Z-Index Layer System

> **⛔ RULE: Follow this layer system. Do NOT invent new z-index values.**
>
> Tokens are defined in `frontend/src/index.css` (`--z-*` block). Always use the CSS variable form (`z-[var(--z-…)]`) — never hardcode numeric values.

| Layer                           | Token              | Class                       | Components                                                                                               |
| ------------------------------- | ------------------ | --------------------------- | -------------------------------------------------------------------------------------------------------- |
| Page content                    | —                  | `z-0`                       | Normal content                                                                                           |
| Sticky headers                  | `--z-sticky`       | `z-[var(--z-sticky)]`       | `sticky` elements within page                                                                            |
| ModuleShell nav                 | `--z-module-nav`   | `z-[var(--z-module-nav)]`   | Module nav (`sticky`, under the top bar), mobile bottom bar, the AppShell notice strip (demo, notifications slot) |
| AppShell top bar                | `--z-app-bar`      | `z-[var(--z-app-bar)]`      | Persistent top bar (`AppShell.tsx`)                                                                      |
| Standard modals                 | `--z-modal`        | `z-[var(--z-modal)]`        | ItemEditModal, ImportModal, StockActionSheet, WebhooksPage                                               |
| Popovers                        | `--z-popover`      | `z-[var(--z-popover)]`      | EmojiPicker, dropdowns anchored to a trigger                                                             |
| Nested modals                   | `--z-modal-nested` | `z-[var(--z-modal-nested)]` | BulkEditModal, the mobile SettingsShell nav sheet, every other `<Sheet zIndex="modal-nested">`           |
| Confirm / high-priority dialogs | `--z-confirm`      | `z-[var(--z-confirm)]`      | ConfirmDialog (ui/), Select, SearchableCombobox (desktop panel; its phone sheet is `modal-nested`), DateInput, AssetStatusMenu, ReplenishSuggestionsModal |
| Fullscreen wizards              | `--z-fullscreen`   | `z-[var(--z-fullscreen)]`   | StorageWizard (onboarding), CookingMode, FinishedScreen, CommandPalette (portaled to `body`)             |
| Notifications & loading screen  | `--z-notification` | `z-[var(--z-notification)]` | NotificationTray, LoadingSpinner (full-screen)                                                           |

A surface that opens over *whatever* is on screen — the command palette, reachable with Ctrl+K from
any sheet or wizard — stands on the highest sheet tier and renders at the end of `body`: equal tiers
paint in document order, so the one opened last lands on top. On a lower tier it opens under the
sheet it was called from, invisible and pointer-dead while it still takes the keyboard. A question it
raises itself (a dirty-form guard) goes on the same tier, or it opens under the surface that asked.

### 4.2 Modal backdrop

**Standard backdrop**: `bg-black/50` (50% opacity)

Use `bg-black/60` only for modals that need stronger separation (sheets with content behind them).
Use `bg-black/80` only for image/scan viewers.
Use `backdrop-blur-sm` sparingly — only for high-priority overlays like category creation or imports.

### 4.3 Bottom sheet pattern (mobile → desktop)

`<Sheet>` is this pattern: a bottom sheet below `sm`, centred above it, with the layer, backdrop,
focus trap and Escape handling built in. Compose it — never hand-roll the `fixed inset-0` wrapper:

```tsx
<Sheet open={isOpen} onClose={onClose} maxWidth="md" aria-label={t("dialogTitle")}>
  <SheetHeader title={t("dialogTitle")} onClose={onClose} />
  <SheetBody>{/* scrollable content */}</SheetBody>
  <SheetFooter>
    <SheetActions>
      <Button variant="outline" onClick={onClose}>{t("common:actions.cancel")}</Button>
      <Button variant="primary" onClick={save}>{t("common:actions.save")}</Button>
    </SheetActions>
  </SheetFooter>
</Sheet>
```

**Form footer (convention):** compact buttons, right-aligned, Cancel (`variant="outline"`) before the primary action; never 50/50 full-width on desktop. On mobile (<sm) the buttons are full-width for touch comfort — but on desktop always compact and right-aligned.

**Do not write those widths at the call site — `SheetActions` owns them.** Every
footer that hand-rolled this row wrote `flex-1` and stopped: that is the phone half
of the rule, and without the `sm:` half the dialog splits down the middle on a
desktop. `SheetActions` states both halves on the row, so a `<Button>` inside it
sets no width at all; `npm run lint:ui` fails on one that does. A button that must
keep its own width says `!flex-none` (the row's selector outranks a plain utility);
content that belongs on the left — a count of what is about to be saved — takes
`mr-auto`.

**One row of actions, and it is about this edit.** A `SheetFooter` holds exactly
one `SheetActions` — `Cancel` and the primary action, primary last. Actions that
act on the _record_ rather than on the edit in progress — Delete, Archive,
Duplicate — go to the `ActionMenu` in the sheet header, beside the close button,
non-destructive first and the destructive ones after the separator. Save and
Cancel speak about changes that exist only while the dialog is open; deleting
speaks about something that outlives it, and the two do not share a block.

That is also the only shape that fits: `SheetActions` gives every button
`flex-1` below `sm`, so a fourth action on a 390px screen leaves four ~90px
buttons. `FormSheetFooter` writes this row for you — prefer it over spelling out
`SheetFooter` + `SheetActions` for a form. `npm run lint:ui` fails on a footer
with more than one action row.

`SheetFooter` is the chrome around it: the separator, the padding, and the bottom
safe-area inset. Use it even where the surface is not a `Sheet` — a page whose
footer is pinned to the bottom of the viewport is the same thing and gets the same
inset. Hand-rolling that inset is how footers ended up with `pb-safe-bottom`, a
utility this project does not define and which therefore did nothing.

**The scroll layer is `SheetBody`.** The `Sheet` panel is `max-h-[90vh] overflow-hidden`, so content taller than the
panel needs a scroll layer of its own: `SheetBody` (`flex-1 min-h-0 overflow-y-auto`).
Without it the tail of the content is clipped and **unreachable** — a `Sheet` locks
`body` scrolling while it is open, so the page underneath will not move either.
`min-h-0` is mandatory: without it a flex child refuses to shrink below its content
size and `overflow-y-auto` never engages. Header and footer stay outside `SheetBody`
so they keep their place while the body scrolls. `npm run lint:ui` fails on a
file that renders a `<Sheet>` with no `SheetBody` and no `overflow-auto` / `overflow-y-auto`
anywhere in it — a hand-written scroll `div` satisfies it, so the layer itself is a review check.

**Backdrop-click-to-close requires the press to have _started_ on the backdrop.**
Guarding `onClick` with `e.target === e.currentTarget` alone is not enough: when an
action on `mousedown` shortens the content (switching a tab, collapsing a section,
removing a row), the dialog shrinks and re-centres, `mouseup` lands on the backdrop,
and the browser dispatches `click` to the nearest common ancestor of the two — the
backdrop. `Sheet` and `ModalShell` already carry that guard; any new overlay shell
must repeat it.

**One Escape closes one layer.** A `Sheet` opened from inside a dialog — the date
picker below `sm:` is the common case — closes itself from its own `document`
listener, while Radix listens for the same key in the capture phase and registered
first. Measured at 390px, one press took down the picker _and_ the campaign dialog
behind it, with everything typed. The same shape appears the other way round: a
sheet opened from inside another sheet — the location list under the storage
wizard's first step — where one press used to close the list _and_ raise the
wizard's discard question over it, with a destructive Discard a click away.
`Sheet` therefore announces itself through `components/ui/overlayStack.ts` while
open, and **only the highest sheet acts on the key**: one standing under another
stands idle, and `DialogContent` prevents the Escape it is handed while a sheet is
stacked above. Any new overlay shell that can be opened from inside a dialog must
register the same way — and one opened from inside a sheet closes under the same
rule.

**A question hands the focus back where it came from.** `ConfirmDialog` is Radix's
alertdialog, whose default returns focus to whatever had it when the question
opened; when that element sat in a list that closed meanwhile, the reader landed
on `body`, outside the sheet, and the next Tab walked the page behind it. The
dialog remembers the element as it opens and restores it on the way out, falling
back to `getTopmostOverlaySheetPanel()` — which is why a `Sheet` panel carries
`tabIndex={-1}`.

**A panel that fills the screen is a sheet on a phone, never a popover.**
`SearchableCombobox` was a Radix popover in both places. Its panel is around 550px
of header, search field and list — more than fits under a trigger halfway down a
form — so Radix flipped it above the trigger and clamped it against the top of the
_layout_ viewport, which on a phone is behind the browser's own chrome. Measured at
390x620: the panel started at -118px and the search field, the first thing the
reader is meant to type into, sat entirely off-screen between -48px and -4px. Below
`sm:` such a panel is a `Sheet` — `DateInput` and `SearchableCombobox` both are.
Above it, the popover states `collisionPadding` and caps its height with
`--radix-popover-content-available-height`, so a short window shrinks the list
instead of pushing the panel off the top of the screen.

**A sheet opened from inside a Radix `DialogContent` is measured against the dialog,
not the screen.** `DialogContent` centres itself with `translate-x-[-50%]
translate-y-[-50%]`, and a transform makes an element the containing block for every
`position: fixed` descendant — so the sheet's `inset-0` resolves to the dialog's box
rather than the viewport. Measured at 390x620 in the putaway-rule dialog, the panel
ran 88px below the bottom of the screen; the date picker has the same geometry there
today. A form that holds a picker belongs in a `Sheet` or a `ModalShell`, neither of
which transforms, until `DialogContent` centres without one.

### 4.4 Centered modal pattern (desktop-only)

There is no desktop-only modal: a `<Sheet>` (§4.3) is already centred from `sm` up. Older
components hand-rolled one with a numeric `z-[100]` and `bg-white`; both break §4.1 and dark mode,
so a component touched for another reason moves to `<Sheet>`.

---

## 5. Form Patterns

### 5.1 Standard form field

```tsx
<Input
  label="Product name"
  placeholder="e.g. Milk 2%"
  value={name}
  onChange={(e) => setName(e.target.value)}
  error={errors.name}
/>
```

Field labels are `font-medium` (as `<Input>` renders them) — never `font-bold` or `font-semibold`.

### 5.2 Form layout

```tsx
<div className="space-y-4">
  {/* Single column */}
  <Input label="Name" ... />

  {/* Two columns */}
  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
    <Input label="Quantity" ... />
    <Select ... />
  </div>

  {/* Section divider */}
  <div className="border-t border-border pt-4">
    <h3 className="text-base font-semibold text-on mb-4">Details</h3>
    {/* more fields */}
  </div>
</div>
```

### 5.3 Error display

```tsx
// Field-level: handled by Input/Select component props
<Input error="This field is required" />

// Form-level error banner
<div className="bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-on-danger font-medium">
  Something went wrong. Please try again.
</div>
```

### 5.4 Checkbox / Toggle

```tsx
import { Checkbox } from "@/components/ui/Checkbox";

<Checkbox label={t("fields.archived")} checked={archived} onChange={(e) => setArchived(e.target.checked)} />
```

A raw `<input type="checkbox">` or a hand-styled toggle `<button>` is not the `<Checkbox>` of §2.1. There is no shared
switch component yet: an on/off setting is a `<Checkbox>`, and the first screen that genuinely needs
a switch adds one to `components/ui/`.

---

## 6. Icon Guidelines

### Library: Lucide React

```tsx
import { Plus, X, ChevronDown, Loader2 } from "lucide-react";
```

### Size standards

| Context              | Size prop | strokeWidth |
| -------------------- | --------- | ----------- |
| Button icon (any)    | `16`      | `2`         |
| Navigation icon      | `20-22`   | `2`         |
| Card header icon     | `24`      | `2`         |
| Hero/decorative icon | `32`      | `1.5`       |
| Icon-only button     | `18`      | `2`         |

### Dynamic icons

```tsx
import { DynamicIcon } from "@/components/ui/DynamicIcon";

// Renders the Lucide icon registered under this name in DynamicIcon's ICON_MAP (any other name: Package)
<DynamicIcon name="Package" size={20} strokeWidth={2} />;
```

---

## 7. Animation Standards

### Transitions

| Element      | Duration                                            | Easing      |
| ------------ | --------------------------------------------------- | ----------- |
| Button hover | `duration-200`                                      | default     |
| Input focus  | `duration-200`                                      | default     |
| Modal open   | `duration-200` (fade) + `duration-300` (`Sheet` slide/zoom; `ui/Dialog` zooms in `duration-200`) | default (`ease`) |
| Card hover   | `duration-200`                                      | default     |
| Color change | `transition-colors`                                 | default     |
| All props    | `transition-all`                                    | default     |

### Modal animations

```
// Backdrop
animate-in fade-in duration-200

// Content (mobile bottom sheet)
animate-in slide-in-from-bottom duration-300

// Content (desktop centered)
animate-in zoom-in-95 duration-200

// Combined (responsive modal)
animate-in slide-in-from-bottom sm:zoom-in-95 duration-300
```

### Button press feedback

```
active:scale-[0.98]
```

---

## 8. Accessibility Checklist

- Modals: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`
- Escape key closes modals
- Focus trap in modals (the first focusable element takes focus on open; Tab and Shift+Tab stay inside — `useFocusTrap`)
- Form labels connected via `htmlFor` / `id`
- Loading states: `disabled` + spinner visual
- Disabled state: `opacity-50` + `pointer-events-none` / `cursor-not-allowed`
- Color contrast: Text on colored backgrounds must meet WCAG AA (4.5:1 for normal text)

---

## 10. Anti-Patterns — NEVER Do This

1. **❌ Inline button styling** — Always use `<Button variant="..." size="...">`. Never write `<button className="px-4 py-2 bg-primary-600 text-white rounded-xl ...">`
2. **❌ Raw `emerald-*` classes** — Use `success-*` for success semantics or `accent-*` for profile-tinted positive emphasis (§1.1, ADR-013)
3. **❌ Raw `slate-*` classes** — Use `gray-*` (zinc-based) token
4. **❌ Arbitrary z-index** — Follow the z-index layer table
5. **❌ Hardcoded hex colors** — Use Tailwind classes
6. **❌ Custom CSS/inline styles** — Use Tailwind utility classes exclusively
7. **❌ `px`, `rem` in inline styles** — Use Tailwind spacing scale
8. **❌ A hand-rolled modal** — every modal is a `<Sheet>` (§4.3), which is a bottom sheet on a phone and centred on a desktop
9. **❌ Missing Escape key handler** — Every modal must close on Escape, unless it is `<Sheet dismissible={false}>` (a one-time secret or generated key)
10. **❌ Missing `disabled` state** — Interactive elements must handle disabled state
11. **❌ Non-standard page width** — Pages outside `ModuleShell` use `<PageContainer>` or `<PageContainer wide>`; module pages use neither (§3.2a). Never use `max-w-2xl`, `max-w-4xl`, `max-w-5xl` as page root containers
12. **❌ Duplicate page padding** — Never add `p-*`/`px-*`/`py-*`/`pt-*`/`pb-*` to `<PageContainer>`; it sets its own `pb-32`, and `AppShell.tsx` provides outer padding
13. **❌ `text-2xl` / `text-3xl` for page titles** — Always `text-lg md:text-xl font-semibold text-on tracking-tight` (see §11.2)
14. **❌ `font-bold` for page titles** — Always `font-semibold`
15. **❌ Decorative icon before page title** — Module identity is in the ModuleShell nav bar, not repeated in page header
16. **❌ Oversized CTA (`h-12 px-6`)** — Use default Button size; use `size="lg"` only for onboarding/wizards
17. **❌ `space-y-4` or `space-y-8` or `space-y-10` on PageContainer** — Always `space-y-6` for consistent vertical rhythm
18. **❌ Raw `<main>` or `<div>` as page root outside `ModuleShell`** — wrap it in `<PageContainer>`. A module page inside `ModuleShell` returns `<div className="space-y-6">` instead (§3.2a)
19. **❌ `dark:text-white` on titles** — `text-on` already handles dark mode via CSS vars
20. **❌ A width or a height in `className` that the component already declares** — use a variant, or `wrapperClassName` for a field's box. `twMerge` drops the plain class and keeps the responsive one, so the override wins on a phone and loses on every desktop (see §2.0)

---

## 11. Page Anatomy Standard (MANDATORY)

> **⛔ Every page in every module MUST follow this anatomy.** This ensures Inventari looks like one product, not a collection of disconnected pages. Inspired by Odoo's module consistency.

### 11.1 The Canonical Page Layout

Every list/dashboard page in a module follows this exact structure. The shell (`ModuleShell`) renders
the header and sizes the page, so the page hands its header to the shell and returns a plain
`<div className="space-y-6">` — no `<PageContainer>`, no `<h1>` (§3.2a, §11.5):

```tsx
const { setHeader } = useModulePageHeader();

useEffect(() => {
  setHeader({
    // title/subtitle when the page needs one beyond the module's own
    actions: (
      <div className="flex items-center gap-2">
        {/* Secondary actions (outline buttons, left) */}
        <Button variant="outline" leftIcon={<FileDown size={16} />}>
          {t("common:actions.export")}
        </Button>
        {/* Primary CTA (always rightmost) */}
        <Button leftIcon={<Plus size={16} />}>{t("addButton")}</Button>
      </div>
    ),
  });
}, [t, setHeader]);

return (
  <div className="space-y-6">
    {/* === TOOLBAR (search + filters) — §11.6 === */}
    <ListControlBar
      search={{ value: search, onChange: setSearch, placeholder: t("searchPlaceholder") }}
    />

    {/* === CONTENT (list / grid / cards) === */}
    {/* ... */}
  </div>
);
```

A page outside any shell (§11.5) renders the same header itself (§11.3) inside `<PageContainer>`.

### 11.2 Page Title Rules

| Token             | Classes                                        | Usage                                                                                               |
| ----------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Page title**    | `text-lg md:text-xl font-semibold text-on tracking-tight` (18px phone, 20px desktop) | ALL page h1 titles. The files ESLint's `<h1>` rule exempts are listed in its `ignores` (`eslint.config.js`). |
| **Page subtitle** | `text-sm text-on-muted mt-0.5 hidden sm:block` | Optional description below title; **desktop-only** (product standard — mobile headers stay compact) |

#### ⛔ RULES

- **NEVER** use `text-2xl` or `text-3xl` for page titles — `text-xl` keeps density.
- **NEVER** use `font-bold` for page titles — `font-semibold` is the standard.
- **NEVER** use `text-on-secondary` for subtitles — always `text-on-muted`.
- **Subtitles are desktop-only** (`hidden sm:block` in `PageHeader`): mobile headers stay compact — the subtitle is supplementary context, not navigation. This is a product-wide standard, not a per-module choice.
- **NEVER** add `leading-none`, `leading-tight`, or `mb-1`/`mb-2` to titles — spacing is controlled by the parent flex gap.
- **NEVER** add a decorative icon (Monitor, ChefHat, etc.) before the page title — module identity comes from the ModuleShell nav, not the page title.
- **NEVER** add `dark:text-white` — `text-on` already handles dark mode via CSS variables.

### 11.3 Page Header Layout

Inside `ModuleShell` or `SettingsShell` the shell's `PageHeader` renders this from what the page passes to
`useModulePageHeader()`; a page there never writes it. The markup below is what `PageHeader` renders, and
what a page outside any shell writes itself. The header is always a `flex` row that stacks on mobile:

```tsx
<div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center justify-between gap-3 sm:gap-4">
  {/* Left: title + subtitle */}
  <div>
    <h1 className="text-lg md:text-xl font-semibold text-on tracking-tight text-balance">{title}</h1>
    <p className="text-sm text-on-muted mt-0.5 hidden sm:block">{subtitle}</p>
  </div>
  {/* Right: action buttons */}
  <div className="flex items-center gap-2">{/* ... buttons */}</div>
</div>
```

#### ⛔ RULES

- **Always** `sm:gap-4` between title block and actions (`gap-3` on a phone, where the actions wrap under the title). Not `gap-6`.
- **Always** `sm:flex-row sm:items-center` for responsive stacking.
- **Never** wrap the CTA in `<Link>` — use `onClick` + `navigate()` or the Button's `onClick`.

### 11.4 Action Button Hierarchy

Buttons in the page header follow a strict hierarchy, **always left-to-right by importance**:

```
[Tertiary: ghost/outline] → [Secondary: outline] → [Primary CTA: default/primary]
```

| Position                    | Variant                        | Size           | Example                             |
| --------------------------- | ------------------------------ | -------------- | ----------------------------------- |
| **Primary CTA** (rightmost) | `variant="primary"` (default)  | default (`md`) | `+ Add Product`, `+ New Stock Take` |
| **Secondary actions**       | `variant="outline"`            | default (`md`) | `Import`, `Export`, `Categories`    |
| **Tertiary actions**        | `variant="ghost"` or icon-only | `sm` or `icon` | Filter toggle, view mode            |

#### ⛔ RULES

- **NEVER** override button height with `className="h-12 px-6"` — use `size="lg"` if you truly need larger buttons (rare).
- **NEVER** use raw `<button>` with inline classes — always `<Button>`.
- **NEVER** use `size="sm"` for page-level CTAs — `sm` is for inline/table actions only.
- **All icon sizes in buttons**: `size={16}` for `leftIcon`/`rightIcon`. Not 18, not 20.
- **Primary CTA always has `leftIcon={<Plus size={16} />}`** when the action is "create/add".
- **An icon-only button carries `aria-label` _and_ `title` — both, with the same
  words.** With no text inside, there is nothing for the accessibility tree to
  read, and the control announces as "button" and nothing more. `title` alone
  does not close the gap: it is the last resort of the accessible-name
  algorithm, screen readers treat it inconsistently, and it never appears on a
  touch screen. The same omission kept coming back in the same module, so
  `recipes` now gates it in `iconButtonNames.test.ts` — copy that test when a
  module accumulates icon buttons.
- **The pointer half of that rule can be carried by the app's own `Tooltip`.**
  That bubble appears on hover **and** on keyboard focus, which `title` never
  does; where it stands, `title` is not set — the browser's bubble opens over
  the app's own a second into the hover. The words are then the same two ways
  as always: the tooltip and the `aria-label`.
- **The mirror of that rule: a button that already shows text must not carry an
  `aria-label`.** `aria-label` replaces the visible label rather than adding to
  it, so putting a tooltip ("Add meals first") on a button reading "Generate
  shopping list" renames the control to the tooltip — the name a user says and
  the name the machine hears stop matching (WCAG 2.5.3).

### 11.5 Page Container Rules

| Page type                                     | Container                                    | Example                                          |
| --------------------------------------------- | -------------------------------------------- | ------------------------------------------------ |
| Module page inside `ModuleShell` (list, detail, settings tab, CRUD) | none — return `<div className="space-y-6">` | Items, Storages, Stats, Asset Detail, Categories |
| Page outside `ModuleShell`, full width        | `<PageContainer wide className="space-y-6">` | App Store (`modules/settings/components/AppStore.tsx`) |
| Page outside `ModuleShell`, standard width    | `<PageContainer className="space-y-6">`      | the focus-mode gate (`components/FocusLockGate.tsx`)   |

#### ⛔ RULES

- **Inside `ModuleShell`, never** use `<PageContainer>` — the shell sizes and pads the page (§3.2a).
- **Outside `ModuleShell`, ALWAYS** use `<PageContainer>`. Never use raw `<div>` or `<main>` as page root.
- **NEVER** add `px-*`, `pt-*`, `py-*`, or `p-*` to `<PageContainer>` — `AppShell.tsx` provides outer padding.
- **NEVER** override `max-w-*` inside `PageContainer` (e.g., `max-w-2xl mx-auto`). If content should be narrow, use a `max-w-2xl` inner wrapper, not on the container.
- **Always** include `space-y-6` on `PageContainer`. This is the standard vertical rhythm for all pages.
- **Optional**: add `animate-in fade-in duration-300` for page entry animation.

### 11.6 Toolbar / Filter Bar

When a page has search, status tabs or filters, it uses `<ListControlBar>` — one component for the
whole row, never a hand-built `<Input>` + `<Button>` row or a row of raw tab `<button>`s:

```tsx
<ListControlBar
  search={{ value: search, onChange: setSearch, placeholder: t("searchPlaceholder") }}
  primaryTabs={{
    value: statusFilter,
    onChange: setStatusFilter,
    options: STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) })),
  }}
  filterButton={/* opens the filter sheet */}
/>
```

#### ⛔ RULES

- Search, status tabs (`primaryTabs`), chip filters (`secondaryFilters`), the filter button and the view
  toggle all go through `ListControlBar`'s props; the component owns their layout, spacing and the
  pill styling of the tabs.
- A filter the props cannot express is a change to `ListControlBar`, not a second bar beside it.

### 11.7 Empty State

Every list page has an empty state, and it is `<EmptyState>` (§13.4), which carries the icon,
type and spacing:

```tsx
<EmptyState
  icon={Package}
  title={t("empty.title")}
  description={t("empty.description")}
  primaryAction={<Button leftIcon={<Plus size={16} />}>{t("empty.action")}</Button>}
/>
```

#### ⛔ RULES

- A CTA only when the reader can act on it: a read-only account gets the title and the
  description, no button it cannot use.
- **A page's empty state carries a title and a description; the CTA belongs
  to the page, not always to the empty state.**
  The title names the absence ("No locations yet"); the description is a
  separate sentence, never the second half of the title. A heading reading
  "No locations yet. Add your first." renders both sentences in heading
  weight and size, so the invitation reads as an error message. The action
  goes in the empty state's `primaryAction` unless the page already shows it
  where the reader looks first — its header, its tab toolbar or the form
  above the list — in which case a second button beside it is a competing
  first move and is left out.
- **A compact empty state inside a card, panel, tab or modal may keep a single
  line** — the description is optional there, and `EmptyState`'s `description`
  prop stays optional for them. The description rule is what a _page_ owes its
  reader.
- `check:empty-state` (part of `make check-frontend`) fails when a file under
  `modules/<module>/pages/**/*Page.tsx`, or a `*EmptyState.tsx` helper a page
  hands its empty state to (anywhere under `modules/<module>/`), renders
  `<EmptyState>` without a `description`. It checks the description only; the
  title and the CTA are for the author and the reviewer.

### 11.8 Detail Page Header (with back navigation)

A detail or edit page inside a shell writes no header of its own (§2.6): it passes `backTo`, and the
shell's `PageHeader` renders the back arrow beside the title. `backTo` is the parent list's path,
not `navigate(-1)` — a page opened from a link has no history to go back to.

```tsx
const { setHeader } = useModulePageHeader();

useEffect(() => {
  setHeader({
    backTo: "/purchase-orders",
    title: po ? po.number : t("title"),
    subtitle: partnerName ?? undefined,
    statusBadge: po ? <StatusBadge status={po.status} /> : undefined,
    actions: <>{/* Actions */}</>,
  });
}, [setHeader, po, partnerName, t]);
```

### 11.9 Settings pages

A module's settings screen (the last item of its nav, §2.14a) is a page a person comes back to a few times a
year, so it is built to be found and read, not to be a form that grew. Three rules, all of them checked the
same way: open the page at 1440x900 and 390x844 and count.

#### ⛔ RULES

- **One save model.** Either one Save for the whole page — it appears, stuck above the bottom nav, only while
  something changed (`<SettingsSaveBar>` with `PageSaveProvider` and `usePageSavePart`, `@/hooks/usePageSave`),
  and the page asks before it is left with unsaved work (the bar arms `useFormGuard` itself) — or every control
  saves on change and says so with a visible confirmation. Never a Save per fragment, and never the two models
  on one page: a select that writes at once next to a text field that waits for a button teaches the reader
  that neither can be trusted. A section that keeps its own state registers it with `usePageSavePart`; it does
  not grow a button of its own.
- **Sections with navigation, not a wall of fields.** More than about one screen of controls is split into
  named sections, one on screen at a time, with a section list beside the content on a desktop and the same
  list as scrolling `<Tabs>` on a phone. Every section stays mounted (`forceMount` and `hidden`) so an edit
  made in one is still waiting for Save after the reader moves to another. The open section may be kept in the
  address (`?section=`) so it can be linked to.
- **Links are navigation, set apart from the fields.** A link to a sub-screen (the rules, the occupancy view,
  the templates) is a plain link in a "Related screens" row at the foot of the section it belongs to
  (`RelatedScreens`), never a card among the inputs. Settings written once and rarely changed (a numbering
  format, the names of document types) sit under an Advanced disclosure inside their section, closed.

Where a page cannot meet a rule yet, the gap is tracked as an issue, not left as a comment in the code.

---

## 12. Quick Decision Matrix

| "I need to..."                    | Use this                                                   |
| --------------------------------- | ---------------------------------------------------------- |
| Show a clickable action           | `<Button variant="..." size="...">`                        |
| Wrap content in a box             | `<Card>` + `CardHeader/Content/Footer`                     |
| Show status text                  | `<Badge variant="...">`                                    |
| Collect text input                | `<Input label="..." error={...}>`                          |
| Choose from a list                | `<Select>` (few items) or `<SearchableCombobox>` (many)    |
| Display an icon                   | Lucide import or `<DynamicIcon name="...">`                |
| Confirm a destructive action      | `<ConfirmDialog>` from `components/ui/`                    |
| Show a full-screen loading state  | `<LoadingSpinner>`                                         |
| Layout 2 fields side by side      | `grid grid-cols-1 md:grid-cols-2 gap-4`                    |
| Start a new list/dashboard page   | Copy the canonical layout from §11.1                       |
| Write a page title                | `text-lg md:text-xl font-semibold text-on tracking-tight` (§11.2) |
| Add a "Create" CTA to page header | `<Button leftIcon={<Plus size={16} />}>` rightmost (§11.4) |
| Add search + filters bar          | Follow toolbar pattern from §11.6                          |
| Show an empty list state          | `<EmptyState>` (§11.7, §13.4)                              |
| Create a detail page with "back"  | Follow detail header pattern from §11.8                    |
| Create a new modal/sheet          | `<Sheet>` from `components/ui/` (§13.3)                    |
| Show an entity status             | `<StatusBadge status={...}>` (§13.2)                       |
| Run one-off action + toast        | `runWithToast(fn, {...})` (§13.1)                          |
| Render loading/error/data states  | `<QueryResult query={...}>` (§13.4)                        |
| Resize or reposition a component  | A variant, or `wrapperClassName` — not `className` (§2.0)  |
| Add an action row to a modal      | `<SheetFooter>` + `<SheetActions>` (§4.3)                  |

---

## 13. Canonical Helpers

Use these helpers instead of writing new hand-rolled copies. The four below are the ones reached for
most; the blocking detectors in `frontend/scripts/ui-patterns/` name the canonical helper for their
own class in the message they print — `useMoney`, the locale formatters in `utils/formatters.ts`,
`extractApiError`, `QueryFailure` / `RecordNotFound`, `useCanWrite` / `ReadOnlyNotice`,
`FormSheetFooter`, `ActionMenu`, `ScrollRow`.

### 13.1 `runWithToast` — one-off async actions with toasts

For **imperative, one-off async calls** (button handlers that call an API function directly, outside React Query), use `runWithToast` from `@/lib/api/runWithToast`:

```tsx
import { runWithToast } from "@/lib/api/runWithToast";

const handleExport = async () => {
  const result = await runWithToast(() => exportCsv(listId), {
    success: t("exportSuccess"),
    errorFallback: t("exportFailed"),
  });
  if (result) downloadFile(result);
};
```

**When NOT to use it:** for standard CRUD mutations that must invalidate React Query caches, keep using `useAppMutation` / module hooks (`useXMutations.ts`) — they handle `queryClient.invalidateQueries`, optimistic updates and pending state. `runWithToast` is for fire-and-forget actions (exports, scans, one-shot commands), not for query-cache-managed mutations.

### 13.2 `StatusBadge` — canonical status pill

Do NOT hand-roll per-module status badge components with local color maps. Use the generic `<StatusBadge>` from `@/components/ui/StatusBadge`:

```tsx
<StatusBadge status={order.status} ns="maker" />           // label via `status.${status.toLowerCase()}` in ns
<StatusBadge status={asset.status} variants={{ BROKEN: "danger" }} />  // extend default variant map
<StatusBadge status={x} label={t("customLabel")} />        // explicit label, skips i18n
```

- Ships a default semantic map (`DRAFT`→secondary, `PENDING`→warning, `ACTIVE`→info, `APPROVED`/`COMPLETED`→success, `CANCELLED`/`REJECTED`→danger, …); override/extend via `variants`.
- Label resolution: the `label` prop; otherwise the translation of `labelKey` when given, else of `${labelKeyPrefix}.${status.toLowerCase()}`; when that key has no translation, the raw status text.

### 13.3 `<Sheet>` — canonical modal container

New modals MUST use `<Sheet>` from `@/components/ui/Sheet` — do NOT hand-roll `fixed inset-0` wrapper markup. §4.3 shows the composition and the rules behind it.

```tsx
<Sheet
  open={isOpen}
  onClose={onClose}
  maxWidth="md"
  aria-label={t("dialogTitle")}
>
  {/* header (with <Button variant="ghost" size="icon"> close), scrollable content, footer */}
</Sheet>
```

- Bottom sheet on mobile, centered on desktop — built in.
- `maxWidth`: `"sm"`…`"6xl"`; `zIndex` tiers per §4.1 (`"modal"` default, `"modal-nested"`, `"confirm"`, `"fullscreen"` — mapped internally to `var(--z-*)`); `backdropOpacity` 50/60/80.
- Inside a Sheet, still use `<Button>` for all clickable actions (close, cancel, submit).

### 13.4 `QueryResult` / `EmptyState` — canonical list states

List pages MUST NOT hand-roll `isLoading ? <Spinner/> : error ? ... : data.map(...)` chains.

```tsx
<QueryResult query={itemsQuery}>
  {(items) =>
    items.length === 0 ? (
      <EmptyState icon={Package} title={t("empty.title")} description={t("empty.desc")} primaryAction={<Button … />} />
    ) : (
      <ItemTable items={items} />
    )
  }
</QueryResult>
```

- `QueryResult` (`@/components/ui/QueryResult`) renders loading (default `<LoadingSpinner/>`), error (default retry panel), or `children(data)`; with no data (null or undefined) it renders nothing unless `renderWhenEmpty` is set.
- `EmptyState` (`@/components/ui/EmptyState`) is the canonical empty state (§11.7 styling built in): `icon`, `title`, `description`, `primaryAction`, `secondaryAction`, `variant="default" | "compact" | "steps"`.

---

## 14. Lists and Vocabulary

The words for the core concepts — storage, location, product, record, on hand, reserved,
available, remove, move — are one table, `docs/MODULE_NAMES.md` ("Domain vocabulary"), with the
words each one retires. §14.2–14.4 below are the rulings that table grew from;
`scripts/check-vocabulary.mjs` fails a retired word in a new or changed English string.

### 14.1 A list of records is a `<table>`

Product-style lists MUST be built from `<table>` / `<thead>` / `<tbody>` / `<tr>` /
`<th scope="col">` / `<td>` — not from `div`s in a CSS grid. A grid gives a sighted
reader columns and gives a screen reader nothing: no cell-to-heading association,
no table navigation, no place to put `aria-sort`.

- The column the list is ordered by carries `aria-sort="ascending" | "descending"`.
  Columns with no bearing on the current order carry no `aria-sort` at all.
- Sorting may still be driven by a control outside the table. `aria-sort` states the
  resulting order; it does not imply the heading is clickable.
- Card layouts on a phone are a separate render branch and stay as they are — this
  rule is about the desktop list.
- A table has no `fr` unit. Translate grid proportions into percentages of the
  flexible total and let `table-fixed` scale them (see `ItemTable`).
- Virtualise with spacer rows, never with absolutely positioned `<tr>` elements: a
  row taken out of flow stops being a row of that table, for layout and for the
  accessibility tree alike.

### 14.1a Row height on the desktop list

A record row on the desktop list is built for reading many at once, not for
looking at one. Its cells carry `py-2` and its thumbnail is `w-10 h-10`
— together under 60px a row, a dozen or more rows on a 900px screen.

The list this rule was written for showed six rows out of 584 records, because
it had grown a `py-4` cell around a 48px thumbnail. Six rows is a viewer, not a
list: the reader scrolls past a hundred screens to reach the end of a warehouse.

- The card branch used on a phone keeps its height — there the row is a touch
  target and 44px is a floor, not a budget.
- If a density switch (comfortable / compact) is ever added, it changes this
  value; it does not exempt the default from having one.

### 14.1b The phone card's content target is measured in width

`ItemMobileCard`'s row button — the thing that opens the product — is left under
the 44px floor on purpose, and this section is the reason written down. Measured
at 390px it is **228 × 38**: five times the floor on the axis a thumb travels
along, and six pixels short on the other. Its height is what the row carries —
name, identifiers, metadata — and the card around it is 118px tall, set not by
the row but by its neighbours: a 44×44 quantity badge on the left, two stacked
44×44 actions on the right.

The floor is written for controls: `h-11 md:h-10`, a height a call site
declares. A full-width row between two columns of controls is not that — the
reader aims at the row, and the 44px targets are already at both ends of it.
Padding the button to 44 would add 6px to every product in a list built for
scrolling, or need a negative margin to hide the padding again. 228 × 38 on
`/inventory/items` is the decision, not a regression.

### 14.2 Location vocabulary — one word for a place

A place stock is kept has one word, at every level of the tree:

| Language | Word         | Example                                          |
| -------- | ------------ | ------------------------------------------------ |
| en       | **Location** | `Cold Storage`, `Receiving`, `Shelf A - Top`     |
| pl       | **Miejsce**  | `Chłodnia`, `Przyjęcia`, `Półka A - góra`        |
| de       | **Lagerort** | `Kühllager`, `Wareneingang`, `Regal A - oben`    |
| fr       | **Emplacement** | `Chambre froide`, `Réception`, `Rayon A`      |
| es       | **Ubicación** | `Cámara frigorífica`, `Recepción`, `Estante A`  |

"Storage", "place", "room", "zone", "spot" and "shelf" (as a generic noun) are not
synonyms to reach for — one concept, one word. The app used to say Storages / storage
location / target location / Locations / Warehouse for the same thing, leaving no way to
tell whether those were five things or one. In Polish, "magazyn" and "lokalizacja" are
retired for a place as well: "Magazyn" is the name of the warehouse module, which
received the word when the container lost it.

Applies to page titles, section headings, counters, empty states, toasts and search
placeholders, in all five languages. Internal identifiers (`zone` in component and
prop names, the `storages` module and route) may lag behind; user-visible strings may
not.

**Direction of movement — two labels, and they are not interchangeable:**

| Where stock comes from | **From location** | `From location`, `Z miejsca`, `Quell-Lagerort` |
| ---------------------- | ----------------- | ---------------------------------------------- |
| Where stock lands      | **To location**   | `To location`, `Do miejsca`, `Ziel-Lagerort`   |

"Output" names the produced _thing_, never the place — "Output product" is right,
"Output location" is a destination wearing the word for a source. The production sheet
and the cook-for-stock window carried "Magazyn wyjściowy" / "Stockage de sortie" /
"Almacén de salida" one line under a subtitle promising a _target_ place; in Polish
that is the exact reverse of the movement, and the mistake is silent — nothing
downstream questions it.

Guarded by `src/i18n/__tests__/movementDirectionVocabulary.test.ts`, which holds the
two windows to the wording the warehouse documents already use (`fields.targetLocation`).

### 14.3 The record is a Product

The thing on a shelf is a **Product**, in every user-visible string and all five
languages. It used to be two things at once: the sidebar and the page title said
"Items" while the subtitle directly beneath them said "Browse and manage your
products", and one sentence in the bulk-edit window used both nouns in a single
breath — "applied to all 3 selected products … unchanged for each item".

Guarded by `src/i18n/__tests__/productVocabulary.test.ts` over the core catalogues
(`items`, `common`, `storages`, `labels` and the `inventory` module in every maintained
language, `scan` in English only), where
the noun can only mean the stocked record.

**Out of scope, deliberately:** `warehouse`, `purchase_orders`, `shopping_lists` and
`stock_takes` use "item" for a _line of a list_. That is a different concept which
happens to share the English word, and telling the two apart is a judgement per
string rather than a rule.

**Internal identifiers may lag behind.** The model is `Item`, the route is
`/inventory/items`, the i18n namespace is `items` — all three stay, exactly as `zone`
does in §14.2.

### 14.4 One action, one name

A control that does the same job MUST carry the same label everywhere, regardless of
the state of the row it sits on. A card whose primary button read "Open" or "Items"
depending on whether the storage had child locations gave one action two names, keyed
to a property the reader could not see. Where a distinction genuinely matters, show it
in the content — the chips listing child locations already did.

### 14.5 One ellipsis — the character, not three dots

A placeholder, a loading label and a "show the rest" line all trail off the same way,
and the catalogue writes that with the ellipsis character:

```json
"selectUnit": "Wybierz jednostkę…",
"searching": "Szukam…"
```

**`…` (U+2026), never `...`.** Three periods wrap and truncate as three glyphs, and a
screen reader may read them out as "dot dot dot". `check-i18n-keys.mjs` fails a run on a catalogue string containing `...`, so a new
label cannot pick the losing side by accident.

### 14.6 The WMS session row — one line, in both sessions

The picking session and the receiving session lay a document line out the same
way, because the same person works both with the same phone, often one after
the other: the product name and its context (location, lot, planned shelf) on
the left, the quantity, the status Badge and the icon actions on the right, all
in one flex row. The receiving row used to stack name, quantity, an uppercase
10px status and then the actions underneath — four lines for facts the picking
row held in one, with a second vocabulary for the state and the actions out of
the place the eye had learned.

Action icons in both rows are `size="icon"` (44px below `md`) and carry an
`aria-label` and the same `title`: two of them sit side by side, and neither has
a visible label, so their position must not be the only thing that says what
they do.
