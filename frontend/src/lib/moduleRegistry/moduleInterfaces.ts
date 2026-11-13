import type { ComponentType } from "react";
import type { LucideIcon } from "lucide-react";
import type { Item } from "@/types";
import type { DocumentMetaData, SlotDataMap } from "./slotProps";
import React from "react";

export interface ModuleRoute {
  path: string;
  component: ComponentType<Record<string, unknown>>;
  exact?: boolean;
  /** When true, renders as a React Router index route (path "/"). */
  index?: boolean;
  /**
   * Modules that must be enabled for the route to render; any one is enough.
   * Omitted means always. Unlike a nav item's `requiresModules`, this is the
   * route's own answer: with none of them on, the address is a 404.
   */
  requiresModules?: string[];
  /**
   * The module whose shell (its `moduleNav` frame) this route renders in,
   * when that is not the module declaring it. The declaring module keeps the
   * screen to itself and the host links to the address from its nav: the
   * host never imports the page. The route exists only while the declaring
   * module is enabled, and only inside the host's shell — with the host
   * switched off the address is a 404.
   */
  shell?: string;
}

export interface SlotContribution {
  slot: keyof SlotDataMap;
  component: React.ComponentType<{ data: unknown }>;
  priority?: number;
}

/**
 * Type-erases a slot component for registry storage.
 * The component's Props are checked at registration time (compile-time),
 * but the registry stores them under a common type.
 * TypedSlot<K> restores full type safety on the consumer side.
 */
export function slotComponent<P extends object>(
  component: React.ComponentType<P>,
): React.ComponentType<{ data: unknown }> {
  return component as React.ComponentType<{ data: unknown }>;
}

export interface LauncherConfig {
  /** i18n key for tile display name. */
  displayName: string;
  /** i18n key for one-line description (shown in App Store). */
  description?: string;
  /** Lucide icon for the tile. */
  icon: LucideIcon;
  /** Grouping category in App Store. */
  category?: "core" | "business" | "analytics" | "integrations" | "system";
  /**
   * Tile accent color as Tailwind class.
   * MUST use design tokens: accent-*, primary-*, blue-*, amber-*.
   * Never raw emerald-*.
   */
  color?: string;
  /** Sort order on launcher. Lower = first. Default: 100. */
  order?: number;
  /** If true, tile always shows and module cannot be deactivated. */
  required?: boolean;
  /**
   * If true, do NOT show tile on launcher (for invisible infra modules
   * like 'spaces', 'printing').
   */
  hidden?: boolean;
  /**
   * Explicit navigation target when tile is clicked.
   * Priority: linkTo > moduleNav.basePath > routes[0].path > "/".
   * Use for modules whose routes are handled externally (e.g. Settings).
   */
  linkTo?: string;
}

export interface ModuleNavItem {
  /** Absolute path (e.g. '/inventory/items'). */
  path: string;
  /** Lucide icon for nav item. */
  icon: LucideIcon;
  /** i18n key for label. */
  labelKey: string;
  /**
   * i18n key for the mobile bottom-nav label. Falls back to `labelKey`.
   * Use when the shared label is too long for a bottom-nav tab at 390px
   * (e.g. pl "Do akceptacji" → "Akceptacje"). Desktop nav keeps `labelKey`.
   */
  mobileLabelKey?: string;
  /** i18n key for the page title (h1). Falls back to labelKey if not set. */
  titleKey?: string;
  /** i18n key for the page subtitle (below h1). Optional. */
  subtitleKey?: string;
  /** Show on mobile bottom nav? Default: true. */
  showOnMobile?: boolean;
  /** Show on desktop horizontal nav? Default: true. */
  showOnDesktop?: boolean;
  /**
   * Show directly in the mobile bottom bar (max ~2 items).
   * Items without mobileBar go into the "More" expandable panel.
   * If NO items have mobileBar, all visible items render in the bar (legacy behavior).
   */
  mobileBar?: boolean;
  /** Sort order. Lower = first. Default: 100. */
  order?: number;
  /** Position on the phone (bar and More panel) when it differs from `order`. */
  mobileOrder?: number;
  /**
   * Optional badge rendered next to the nav label (e.g. a pending-approval
   * count). The component owns its own data fetching. Rendered only when
   * present, in both the desktop submenu and the mobile bottom nav.
   */
  Badge?: ComponentType;
  /**
   * Roles that may see this entry. Omitted means everyone in the module.
   *
   * For screens whose API is role-gated: an entry the reader can click and
   * cannot open is worse than no entry, because the refusal arrives looking
   * like a failure. Superusers pass every gate. The screen behind it must
   * still handle the refusal — a hidden nav entry is not access control.
   */
  roles?: string[];
  /**
   * Modules that make this entry worth offering. Omitted means always.
   *
   * For a screen whose subject only exists once some other module is
   * installed: the movement ledger fills up only for organizations whose
   * modules record movements, so for a household it could only ever open an
   * empty page — an entry that never fills is a promise the product cannot
   * keep. Any one of the listed modules is enough. Like `roles`, this hides
   * the entry and is not access control: the screen behind it stays reachable
   * by URL and answers honestly (an empty ledger is an answer, not a 404).
   */
  requiresModules?: string[];
}

export interface ModuleNavConfig {
  /** Items shown in the module's context navigation bar. */
  items: ModuleNavItem[];
  /** Base path prefix for this module (e.g. '/inventory'). Used by ModuleShell. */
  basePath: string;
}

export interface ActionItem {
  /** Unique key. */
  id: string;
  /** i18n key for action text (e.g. 'inventory:launcher.lowStockAlert'). */
  labelKey: string;
  /** Interpolation values for the label (e.g. `{ count: 3 }`). */
  labelValues?: Record<string, unknown>;
  /** Lucide icon. */
  icon: LucideIcon;
  /** Severity affects visual style. */
  severity: "info" | "warning" | "error";
  /** Route to navigate to on click. */
  linkTo: string;
  /** Dynamic count (e.g. number of alerts). */
  count?: number;
}

export interface NavOverride {
  /** Core nav item path to override (e.g. "/inventory/locations") */
  targetPath: string;
  /** Replacement icon */
  icon?: LucideIcon;
  /** Replacement i18n label key */
  labelKey?: string;
  /** When true, removes this item from navigation entirely */
  hidden?: boolean;
}

/**
 * A core section a standalone module either adopts under its own banner or
 * explicitly gives up. These are the pieces of the inventory surface whose
 * absence would otherwise break a promise the module made: a printed equipment
 * label has to keep scanning, so the label pool and the scanner must be
 * accounted for — adopted or renounced, never silently dropped.
 */
export type AdoptableCoreSection =
  "labels" | "scan" | "stats" | "stock_takes" | "archive";

/**
 * A core navigation section a standalone module needs to keep visible even in
 * single-module mode. A module that stands entirely alone leaves this empty;
 * one that "stands alone except the pantry" names the section it keeps.
 */
export type CoreNavSection =
  "items" | "storages" | "categories" | "stock" | "moves";

/**
 * A module's declaration that it can stand alone as the single focus module.
 *
 * Declaring this — not any organization setting — is what makes the module a
 * candidate for single-module mode: only the module's author knows what it
 * needs to stand; the organization flips one switch and never sees the detail.
 * The declaration is what the reachability gate checks, so "this module stands
 * alone" is a verifiable fact rather than a sentence in a comment.
 */
export interface BackgroundFeatureDeclaration {
  provider: string;
  feature: string;
  labelKey: string;
}

export interface StandaloneDeclaration {
  /** Features opened over the focused module rather than through provider routes. */
  backgroundFeatures?: BackgroundFeatureDeclaration[];
  /**
   * For every core section the module's workflow touches, adopt it under the
   * module's own banner or renounce it explicitly. A section left unaccounted
   * for is what breaks a printed label's scan once the core navigation is
   * hidden, so the gate requires the full set to be covered.
   */
  coreSections: Record<AdoptableCoreSection, "adopt" | "renounce">;
  /**
   * Core navigation sections that stay visible in single-module mode. Empty for
   * a module that stands entirely alone; a single entry for the "standalone
   * except this section" shape (recipes keeps the pantry, maker the warehouse).
   */
  keepCoreNav?: CoreNavSection[];
}

export interface LabelPurposeConfig {
  /**
   * The ``context_tag`` stamped on every label generated for this purpose.
   * A scan of an unassigned label reads it back and opens that module's add
   * form (see ScanPage). Must match the tag the module's categories carry.
   */
  contextTag: string;
  /** Lucide icon shown next to the purpose in the generate form and the pool list. */
  icon: LucideIcon;
  /** i18n key for the purpose name (e.g. 'equipment:labels.purpose'). */
  labelKey: string;
  /**
   * Short-code prefix suggested when this purpose is picked (e.g. 'EQP').
   * A separate prefix is what makes a printed sheet recognisable by eye —
   * the tag alone is invisible on paper.
   */
  defaultPrefix: string;
}

/**
 * A module-contributed section that appears in SettingsShell's sidebar
 * and is rendered as a child route under /settings/.
 */
export interface SettingsSection {
  /** i18n key for the section title in the sidebar (e.g. 'webhooks:navigation.webhooks'). */
  title: string;
  /** Route suffix under /settings/ (e.g. 'webhooks' → /settings/webhooks). */
  path: string;
  /** Lucide icon shown in the sidebar. */
  icon?: LucideIcon;
  /** Page component to render. */
  component: ComponentType;
  /**
   * The permission that opens the section, when it is not `admin:access`:
   * the key the section's own API asks for. A section opened by
   * `admin:access` while its API asked for another key could not be used by
   * a custom role holding that key (see `components/settingsAccess.ts`).
   */
  permission?: string;
}

export interface BulkAction {
  id: string;
  labelKey: string;
  icon: LucideIcon;
  handler: (itemIds: string[]) => Promise<void>;
  /** If provided, action is only shown when this returns true. */
  condition?: (items: { id: string }[]) => boolean;
  variant?: "default" | "danger";
  moduleName: string;
}

/**
 * Core forms a module may contribute validation to.
 *
 * A closed union rather than `string`: the previous free-form field made every
 * rule a guess, since a typo produced a rule that silently never matched any
 * form. Adding a form here is the deliberate act of opening it to modules,
 * and a form that is listed has to run the rules (`useModuleValidation`):
 * `storage_create` and `storage_edit` were listed while no location form ran
 * a rule, so a module's rule for them was accepted and never ran.
 */
export type CoreFormName = "item_create" | "item_edit";

/**
 * A validation rule a module contributes to a core form.
 *
 * Rules run on submit, after the form's own validation. Core errors win: a
 * rule cannot overwrite a message the form already produced for that field,
 * only add one where the form found nothing wrong.
 *
 * A rule that throws is logged and skipped — a module must not be able to
 * wedge a core form shut. Returning a message is how a rule blocks a save;
 * throwing is a bug in the rule, and is treated as one.
 */
export interface ValidationRule {
  /** Core form this rule applies to. */
  form: CoreFormName;
  /**
   * Field name to validate, or '*' for cross-field validation.
   *
   * A '*' rule receives `undefined` as its value and the whole form as its
   * second argument; its message is attached to the form-level error key.
   */
  field: string;
  /** Returns an error message string, or null if the value is valid. */
  validator: (
    value: unknown,
    formData: Record<string, unknown>,
  ) => string | null;
  priority?: number;
}

/**
 * A filter chip a module adds to a Core list.
 *
 * Core must not filter by a module's own attribute — "has a formula" belongs
 * to maker, not to the product list — so the module supplies the answer as a
 * set of template ids and Core narrows to it with a neutral filter. The table
 * is virtualised, which is why this cannot be a per-row predicate: the page
 * only holds the rows currently on screen.
 */
export interface ListFilterContributor {
  /** Unique key for the chip. */
  key: string;
  /** i18n key (with namespace) for the chip label. */
  label: string;
  /** The module that must be enabled for this chip to appear. */
  requiredModule: string;
  /** Cache key for the id set (see `queryKeys`). */
  queryKey: readonly unknown[];
  /**
   * Fetches the product template ids the chip narrows to.
   *
   * A plain function rather than a hook: the consumer runs these through
   * `useQueries`, so the number of chips can change when a module is enabled
   * or disabled without breaking the rules of hooks.
   */
  fetchTemplateIds: () => Promise<string[]>;
}

export interface ColumnContributor {
  /** Unique key for this column (e.g. 'warranty_expires'). */
  key: string;
  /**
   * i18n key (with namespace, e.g. 'mymodule:column.warranty') for the table
   * header label. Consumers resolve it via t(); falls back to the raw string
   * when no translation exists.
   */
  label: string;
  /** Renders the cell content for a given item. */
  render: (item: Item) => React.ReactNode;
  /** The module that must be enabled for this column to appear. */
  requiredModule: string;
  /** Where to insert the column relative to existing columns. */
  position?: "before-actions" | "after-name";
  /** CSS width value, e.g. '1fr', '120px'. Defaults to '1fr'. */
  width?: string;
  /**
   * Whether this item would put anything in the column. Tables hide the
   * column when no row on the page answers `true`, so a column that is empty
   * for the current data does not take width from the ones that are not.
   */
  hasValue?: (item: Item) => boolean;
  /**
   * The same question when the answer is not on the row — "does this product
   * have a formula?" lives behind a query, and every product carries a
   * template, so a template-shaped predicate answers yes for a column of
   * blanks.
   *
   * A React hook, called once per table with the rows on the page. Return
   * `undefined` while the answer is still loading; the column stays out until
   * it is known. Takes precedence over `hasValue`.
   */
  useHasValues?: (items: Item[]) => boolean | undefined;
}

/**
 * A warehouse document as a module's column, filter or action sees it.
 * Deliberately small, like the slots' line views: the document's working
 * shape is the warehouse module's own business, this is what a module that
 * keeps its own fields on a document needs to read them back.
 */
export interface DocumentView {
  id: string;
  /** `IN`, `OUT`, `INT`, … — the document's canonical type. */
  type: string;
  number: string;
  /** `DRAFT`, `CONFIRMED`, `PENDING_APPROVAL`, `COMPLETED`, `CANCELLED`. */
  status: string;
  /** What modules keep on the document, each under its own name. */
  metaData: DocumentMetaData;
  /**
   * The document's lines. On the documents list (a column's `render` and
   * `hasValue`) only the lines that carry a module's fields are here — the
   * list does not carry the others; on the document's own screen (an
   * action) every line is.
   */
  lines: {
    id: string;
    batchNumber: string | null;
    /** What modules keep on the line, each under its own name. */
    metaData: DocumentMetaData;
  }[];
}

/**
 * A column a module adds to the documents list (History) — the same idea as
 * {@link ColumnContributor} on the product list, keyed by document. Shown
 * while the contributing module is enabled.
 */
export interface DocumentColumnContributor {
  /** Unique key for this column within the module. */
  key: string;
  /**
   * i18n key (with namespace) naming the column. The list has no header
   * row, so it is printed above each value.
   */
  label: string;
  /** Renders the cell for one document. */
  render: (doc: DocumentView) => React.ReactNode;
  /**
   * Whether this document would put anything in the column. The list hides
   * the column when no row on the page answers `true`; without it the column
   * is always shown.
   */
  hasValue?: (doc: DocumentView) => boolean;
}

/**
 * A filter chip a module adds to the documents list. The narrowing happens on
 * the server, where the count and the paging are: the module registers a
 * provider under the same name with `warehouse_api.register_document_filter`,
 * and the list asks for `<module>:<key>` while the chip is on.
 */
export interface DocumentFilterContributor {
  /** The name the module's backend registered the filter under. */
  key: string;
  /** i18n key (with namespace) for the chip label. */
  label: string;
}

/**
 * A button a module adds to a document's action row, beside Confirm, Post and
 * the PDF. Offered to a reader who may write documents, while the module is
 * enabled; the page reads the document again once `run` resolves, so what the
 * action changed shows at once.
 */
export interface DocumentActionContributor {
  /** Unique key for this action within the module. */
  key: string;
  /** i18n key (with namespace) for the button label. */
  label: string;
  icon?: LucideIcon;
  /** Whether the action belongs on this document; left out otherwise. */
  isAvailable?: (doc: DocumentView) => boolean;
  /**
   * What the press does. Resolve with an i18n key (with namespace) to have
   * its sentence shown as the outcome, or with nothing. A rejection shows its
   * message: throw a `ReadableError` (from `@/module-sdk`) with a sentence for
   * the reader, and a refused request to the module's own API shows its 4xx
   * message as is.
   */
  run: (doc: DocumentView) => Promise<string | void>;
}

export interface SearchResult {
  id: string;
  title: string;
  subtitle?: string;
  path: string;
  module: string;
}

export type SearchProvider = (query: string) => Promise<SearchResult[]>;

export interface FrontendModule {
  name: string;
  routes: ModuleRoute[];
  slots?: SlotContribution[];
  /** Bulk actions contributed to the Items list selection bar. */
  bulkActions?: Omit<BulkAction, "moduleName">[];
  /**
   * Validation rules contributed to core forms. Run on submit; see
   * {@link ValidationRule} for what a rule may and may not do.
   */
  validationRules?: ValidationRule[];
  // `permissions` used to be declared here too, and nothing read it. Modules
  // declare permissions in their backend manifest.json; the roles UI renders
  // them from GET /roles/permission-catalog. See MODULES_GUIDE.
  /**
   * Navigation overrides applied when this module is enabled.
   * Can hide, relabel, or re-icon any core or module nav item.
   * Evaluated per-organisation (reflects `enabledModules` for the active org).
   */
  navOverrides?: NavOverride[];
  /**
   * Declares that this module can stand alone as the single focus module, and
   * how it accounts for the core sections it touches. Presence — not any
   * organization setting — is what makes it a candidate for single-module mode.
   * See {@link StandaloneDeclaration}.
   */
  standalone?: StandaloneDeclaration;
  /** Embedded, route-free surfaces offered to focused modules. */
  backgroundFeatures?: Record<string, ComponentType>;
  /**
   * Translations injected while this module is enabled.
   * Allows renaming core concepts (e.g. "Products" → "Assets") per-organisation.
   * Shape: { [lang]: { [i18nKey]: translatedString } } where the key carries
   * its namespace — "inventory:nav.items"; no prefix means "common". The key
   * must be one a reader actually passes to t() — the i18nOverridesGate test
   * rejects keys missing from the shipped bundles or read by nobody.
   * Originals are restored when the module is disabled.
   */
  i18nOverrides?: Record<string, Record<string, string>>;
  /**
   * CSS variable overrides applied to <html> when this module is enabled.
   * Allows modules to re-skin brand colors (primary/accent palette).
   * Shape: { '--color-primary-500': '139 69 19', ... }
   * Applied on top of the active dark/light theme — compose freely.
   */
  theme?: {
    cssVariables: Record<string, string>;
  };
  /**
   * Label purpose contributed by this module.
   *
   * Blank labels used to be untyped: whatever was scanned opened the product
   * form, because nothing ever stamped a ``context_tag`` on a generated
   * label. A module that owns a different kind of record declares its purpose
   * here, the generate form offers it, and the sticker itself carries the
   * answer — so the scan needs no mode switch to guess from.
   */
  labelPurpose?: LabelPurposeConfig;

  /**
   * Settings sections contributed by this module.
   * Each section appears in SettingsShell's sidebar and renders at /settings/{path}.
   * SettingsShell opens each one to `admin:access`, or to the section's own
   * `permission` when it names one.
   */
  settingsSections?: SettingsSection[];

  /**
   * Launcher tile configuration.
   * Modules without this are invisible on the launcher.
   * Set `hidden: true` for infrastructure modules (printing, spaces).
   */
  launcher?: LauncherConfig;

  /**
   * Column contributors for the ItemTable.
   * Automatically registered when the module calls moduleRegistry.register().
   */
  columnContributors?: ColumnContributor[];

  /**
   * Filter chips this module adds to the Core product list.
   * Automatically registered when the module calls moduleRegistry.register().
   */
  listFilterContributors?: ListFilterContributor[];

  /** Columns this module adds to the documents list (History). */
  documentColumnContributors?: DocumentColumnContributor[];

  /** Filter chips this module adds to the documents list (History). */
  documentFilterContributors?: DocumentFilterContributor[];

  /** Buttons this module adds to a document's action row. */
  documentActionContributors?: DocumentActionContributor[];

  /**
   * Module-internal navigation configuration.
   * Drives the horizontal desktop nav bar and mobile bottom nav bar in ModuleShell.
   * Replaces global `navItems` for context-scoped navigation.
   * @deprecated navItems — use moduleNav.items instead (navItems kept for backward compat).
   */
  moduleNav?: ModuleNavConfig;

  /**
   * React hook returning action items for the launcher feed ("Things to do").
   * Called inside a React component context (may use useQuery, useState, etc.).
   * Must handle loading/error states internally — return empty array while loading.
   * Called for every enabled module whatever the role may read: ask the
   * endpoint only when the role holds the read it guards (`useHasPermission`),
   * and return an empty array otherwise.
   */
  useActionItems?: () => ActionItem[];

  /**
   * React hook returning a status badge for the launcher tile.
   * Called inside a React component context (may use useQuery, etc.).
   * Returns null while loading or when there's nothing to show, and
   * `failed: true` when the read failed (the tile says it could not be read).
   * The tile shows no badge until the hook answers; nothing times it out.
   *
   * `labelKey` is an i18n key in full form (`"inventory:statusBadge.alerts"`),
   * which the tile translates with `{ count }` — the way an action item's
   * `labelKey` is translated by the feed, so both hooks hand over a key.
   */
  useStatusBadge?: () => {
    count: number;
    labelKey: string;
    failed?: boolean;
  } | null;

  /**
   * The read the badge's endpoint asks for (`"equipment:read"`). The launcher
   * shows the tile of every enabled module, whatever the signed-in role may
   * read, and calls `useStatusBadge` only for a role holding this key: for
   * any other role the endpoint would refuse, and the tile would say its
   * status could not be read. Omitted, the badge is asked of every role.
   */
  statusBadgePermission?: string;

  /**
   * Search provider for the command palette.
   * Returns matching results for a given query string.
   * Only called when this module is enabled.
   */
  searchProvider?: SearchProvider;
}
