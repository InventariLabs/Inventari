/**
 * The frontend module SDK — the one door through which a module reaches Core.
 *
 * A module in this tree and a module distributed on its own see the same
 * application, so they import from the same place. `@/module-sdk` re-exports
 * what a module may use: the registry and its contract types, the API client,
 * the design system, the hooks that report what the signed-in user may do, and
 * the few helpers a module screen would otherwise reach for. Anything under
 * `@/` that is not re-exported here is Core's own business.
 *
 * `check-module-boundaries.mjs` enforces it: a module importing `@/…` outside
 * this file is a finding. The modules written before this door existed are
 * baselined by module and path — the list records what they already depend on
 * and cannot grow.
 *
 * Adding a name is not a breaking change: a module can ignore an export it does
 * not use. Removing or renaming one is, because a module compiling against it
 * stops compiling — the same rule the backend's module signatures follow.
 */

// The registry and every type a `FrontendModule` declaration may mention.
export * from "@/lib/moduleRegistry";
export type * from "@/lib/moduleRegistry/moduleInterfaces";
// Where a screen offers a place other modules fill, typed by `SlotDataMap`.
export { TypedSlot } from "@/components/Slot";

// The pre-configured client, with base URL, auth header and refresh handling,
// and the reader that follows a paged list to its end.
export { api, getEveryPage } from "@/lib/api/client";
export type { Page } from "@/lib/api/client";
// What lies where: the stock list, paged and searchable by product or batch.
export { stockQuantsApi } from "@/lib/api/stockQuants";
export type { StockQuantRow } from "@/lib/api/stockQuants";
// The QR label pool: generating, assigning, freeing and exporting labels.
export { labelsApi } from "@/lib/api/labels";

// Helpers a module screen needs: class names, dynamic translation keys, and a
// copy action that explains itself when the browser refuses.
export { cn } from "@/lib/utils";
export { makeTDynamic } from "@/lib/i18nHelpers";
export { copyTextOrExplain } from "@/lib/clipboard";
// A value a screen remembers in the browser between visits, read and written
// as JSON, with a fallback when it is missing or unreadable.
export { readJson, writeJson } from "@/lib/localStorage";
// The sentence to show for a failed request: the server's own message, in the
// reader's language, or the fallback the caller passes when there is none.
export { extractApiError } from "@/lib/errors";
// The error a callback throws to put its own sentence on the screen that asked.
export { ReadableError } from "@/lib/errors";
// A location on one line, its own name before the path, as every location
// picker names it.
export { storageLeafLabel } from "@/utils/storageLeafOption";
export { effectiveExpiry } from "@/utils/effectiveExpiry";

// What the signed-in user may do, and the page header ModuleShell renders.
export { useCanWrite } from "@/hooks/useCanWrite";
// A single permission key, for a right another module's manifest declares —
// a screen offering an approval decision asks `approvals:approve` here.
export { useHasPermission } from "@/hooks/useHasPermission";
export { useHasRole } from "@/hooks/useHasRole";
export { useModulePageHeader } from "@/hooks/useModulePageHeader";
// Whether the history holds an earlier screen of the app to go back to, for a
// dialog that closes by going back to the link that opened it.
export { hasHistoryToPop } from "@/hooks/useShellBack";
// The product profile the organization runs, for wording that follows it.
export { useActiveProfile } from "@/hooks/useActiveProfile";
// A list read that stays quiet while its module is switched off, or while the
// organization's module set is still loading.
export { useModuleQuery } from "@/hooks/queries/useModuleQuery";

// The country list an address or a tax rule is asked from, and the browser
// locale's guess at one.
export {
  COUNTRY_CODES,
  countryFromLocale,
  countryLabel,
} from "@/lib/countries";

// The partner role sets, so a supplier field and the server's validation name
// the same partners.
export { SUPPLIER_ROLE_TYPES } from "@/hooks/partnerRoles";

// The design system. A module builds with these, never with raw HTML controls
// or its own copy of a dialog.
export { Badge } from "@/components/ui/Badge";
export { Button } from "@/components/ui/Button";
export { Checkbox } from "@/components/ui/Checkbox";
export { Input } from "@/components/ui/Input";
// The one look a field label has, for a control that places its own label.
export { FIELD_LABEL_CLASS } from "@/components/ui/fieldLabel";
export { NativeSelect } from "@/components/ui/NativeSelect";
export { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
export { CardLink } from "@/components/ui/CardLink";
export { CompositionBar } from "@/components/ui/CompositionBar";
export { Textarea } from "@/components/ui/Textarea";
// A quantity field, and the step a unit's precision allows: the same floor
// the store rounds to, said as a sentence before the server refuses it.
export { QuantityInput } from "@/components/ui/QuantityInput";
export { quantityStepMessage, useUomPrecision } from "@/hooks/useUomPrecision";
export { ConfirmDialog } from "@/components/ui/ConfirmDialog";
export { EmptyState } from "@/components/ui/EmptyState";
export { QueryResult } from "@/components/ui/QueryResult";
export { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
// The one Save of a settings page: sections register their edit with the
// provider, and the bar writes them together (UI_GUIDELINES §11.9).
export { SettingsSaveBar } from "@/components/ui/SettingsSaveBar";
export {
  PageSaveProvider,
  usePageSave,
  usePageSavePart,
  useUnderPageSave,
} from "@/hooks/usePageSave";
export { SelectionToolbar } from "@/components/ui/SelectionToolbar";
// A panel a module opens itself over a dialog or a sheet: the focus stays
// inside it, and the overlay stack knows it is open, so one Escape closes the
// highest layer only, not the dialog under it as well.
export { useFocusTrap } from "@/hooks/useFocusTrap";
export { registerOverlaySheet } from "@/components/ui/overlayStack";
export { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
export { scanLookupError } from "@/lib/scan/toastScanError";

// Where goods stand. A screen never holds the organization's locations: it
// searches them (LocationCombobox), names the ones its rows stand in by id,
// asks what a scope offers from two rows, and opens a tree branch by branch.
export { LocationCombobox } from "@/components/LocationCombobox";
export { LocationSearchFailed } from "@/components/LocationSearchFailed";
export {
  useLocationOffer,
  useLocationPages,
  useLocationSearch,
  useLocationsById,
  useOfferedLocations,
} from "@/hooks/queries/useLocations";
export { locationScopeParams } from "@/hooks/queries/useLocations";
export type { LocationScope } from "@/hooks/queries/useLocations";
export { locationOption, useLocationPicker } from "@/hooks/useLocationPicker";
export { useStoragesTree } from "@/hooks/queries/useStoragesTree";
export type { LocationOption } from "@/hooks/useLocationPicker";
export { useDebounce, useDebouncedCallback } from "@/hooks/useDebounce";
export { default as Pagination } from "@/components/ui/Pagination";

// Generated wire types and the helper a create payload uses when a field may be
// left to the server's default.
export type { components } from "@/types/api-generated";
export type { WithServerDefaults } from "@/types/request";
