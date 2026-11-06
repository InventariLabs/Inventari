import type { ReactNode } from "react";

/**
 * Product picked from the search dropdown. Structurally identical to
 * `ProductSearchResult` from the documents API — adapters map 1:1.
 */
export interface LineItemProduct {
  product_template_id?: string | null;
  /** Present when the search was scoped to stock in a location. */
  item_id?: string | null;
  available_quantity?: number | string | null;
  /** What makes two rows of one product on one shelf two rows. */
  expiry_date?: string | null;
  serial_number?: string | null;
  /** When this record landed — per-record stock rows only; a merged row is
   *  a shelf total and has no single date. The third thing that tells two
   *  unmarked twins apart besides their quantity. */
  created_at?: string | null;
  /** The shelf a hit stands on — the search walks a location's subtree. */
  location_name?: string | null;
  uom_symbol?: string | null;
  name: string;
  sku?: string | null;
  barcode?: string | null;
  brand?: string | null;
  image_url?: string | null;
  uom_id?: string | null;
  /** Catalogue hits only: what the product last cost, when it has a price. */
  purchase_price?: string | number | null;
}

/**
 * Unified line shape for document and purchase-order editors.
 * Adapters map their module line types onto this:
 * - documents: `ReceiptDraftLine._key` → `key`
 * - purchase orders: `POLineInput.id` → `key`, `quantity_ordered` → `quantity`
 */
export interface LineItem {
  key: string;
  item_id?: string | null;
  product_template_id?: string | null;
  name: string;
  sku?: string | null;
  barcode?: string | null;
  brand?: string | null;
  image_url?: string | null;
  quantity: number;
  uom_id?: string | null;
  unit_price?: string;
  tax_rate?: string;
  batch_number?: string;
  serial_number?: string;
  expiry_date?: string;
  notes?: string;
}

/**
 * Per-line validation errors, keyed to the line's `key`. Passed by the parent
 * form (e.g. DocumentFormModal) so each row can render inline errors next to
 * the offending field. Keys are stable line keys, not array indices, so
 * errors stay attached after remove/reorder/consolidate.
 */
export interface LineItemErrors {
  name?: string;
  quantity?: string;
  unit_price?: string;
  tax_rate?: string;
}

export type LineItemsMode = "document" | "purchase-order";

export interface LineItemsEditorFeatures {
  scan?: boolean;
  quickAdd?: boolean;
  consolidate?: boolean;
  optionalFields?: boolean;
  valueFields?: boolean;
  taxField?: boolean;
  totals?: boolean;
}

/**
 * A search narrowed to one place — the source location of an issue or a
 * move. The list says so, and a product that stands only somewhere else is
 * shown with that place instead of being reported as not found.
 */
export interface LineItemSearchScope {
  /** What the list is limited to, e.g. "Products in Dry Goods". */
  hint: string;
  /** Matches that stand outside the scope; empty while there are none. */
  elsewhere: LineItemProduct[];
  /** Where one of them stands, e.g. "in Fridge B". */
  elsewhereLabel: (storage: string) => string;
  /** The way out, e.g. "Change source location". */
  changeLabel: string;
  onChange: () => void;
}

/**
 * The way out of a search that found nothing, where a line has to name a
 * catalogue product: the typed name becomes a new product instead of
 * staying a line nobody can find again.
 */
export interface LineItemCreateNew {
  /** The offer, e.g. "Add “Dell laptop” as a new product". */
  label: (name: string) => string;
  onCreate: (lineKey: string, name: string) => void;
}

export interface LineItemSearchState {
  results: LineItemProduct[];
  isLoading: boolean;
  scope?: LineItemSearchScope;
  createNew?: LineItemCreateNew;
  onQuery: (query: string) => void;
  onClear: () => void;
}

export interface LineItemsScanState {
  open: boolean;
  loading: boolean;
  error: string | null;
  cameraActive: boolean;
  torchOn: boolean;
  /** The camera that started has a torch; without one no button is drawn. */
  torchAvailable: boolean;
  onToggle: () => void;
  onToggleTorch: () => void;
  /**
   * Typing a code instead of scanning it. Without it the scan panel
   * is a camera or nothing: a desktop with no webcam, or a phone whose camera
   * permission was refused, leaves the reader with a code in their hand and
   * no way to enter it.
   */
  onManualCode?: (code: string) => void;
}

export interface LineItemsTotals {
  subtotal: string;
  tax: string;
  total: string;
}

export type RenderUomSelect = (
  value: string | null,
  onChange: (uomId: string | null) => void,
) => ReactNode;

export interface LineItemsEditorLabels {
  lines: string;
  addLine: string;
  scanOpen: string;
  scanClose: string;
  scanHint: string;
  torchOn: string;
  torchOff: string;
  emptyHint: string;
  item: string;
  quantity: string;
  unit: string;
  unitPrice: string;
  lineValue: string;
  taxRate: string;
  /**
   * What the field will mean if it is left blank — a rate the server applies
   * on its own. Optional: an editor whose blank really is zero passes none.
   */
  taxRatePlaceholder?: string;
  removeLine: string;
  clearProduct: string;
  noResults: string;
  /** Said under `noResults` where a line nobody found is kept as typed in. */
  noResultsAdHoc?: string;
  /** Prefixes the quantity on a stock hit, e.g. "In stock: 7 pcs". */
  inStock?: string;
  expiryLabel?: string;
  /** Prefixes the shelf a stock hit stands on, e.g. "Location: Regal A". */
  storageLabel?: string;
  /** Prefixes a stock hit's landing date, e.g. "Added: 12 Sep 2026". */
  addedLabel?: string;
  adHocBadge?: string;
  adHocBadgeTooltip?: string;
  scanOpening?: string;
  scanProcessing?: string;
  /** Manual code entry inside the scan panel — required with `onManualCode`. */
  scanManualLabel?: string;
  scanManualPlaceholder?: string;
  scanManualSubmit?: string;
  showOptionalFields?: string;
  hideOptionalFields?: string;
  consolidate?: string;
  batchNumber?: string;
  serialNumber?: string;
  expiryDate?: string;
  expiryFieldHiddenHint?: string;
  showExpiryField?: string;
  hideExpiryField?: string;
  notes?: string;
  subtotal?: string;
  taxAmount?: string;
  total?: string;
}

export interface LineItemsEditorTestIds {
  shell?: string;
  desktopHeader?: string;
  rowLayout?: (index: number) => string;
  optionalPanel?: (index: number) => string;
}
