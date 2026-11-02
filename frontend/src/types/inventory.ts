// Inventory / item / storage types.
import type { components } from "./api-generated";

/**
 * A storage type. Taken from the schema rather than retyped: the
 * hand-written copy narrowed `behavior_mode` to the four modes the food
 * tree ships with, where the backend types a plain string — the same
 * narrowing that broke `Category.category_type` for every other vertical.
 */
export type StorageType = components["schemas"]["StorageType"];

/**
 * A storage location, as the detail endpoints answer. Taken from the schema
 * rather than retyped: the hand-written copy folded two wire shapes into one
 * — `user_id` (never sent) and the list endpoint's computed counts and
 * `full_path`, which live on `StorageLocationSummary` and were promised here
 * to every reader of a detail response.
 */
export type StorageLocation = components["schemas"]["StorageLocation"];

/**
 * One row of `GET /locations/archived` — identity plus when it left the lists.
 *
 * `full_path` is a location's identity in this application (the active
 * listing's path, the cards' parent overline), and the archive is where
 * picking wrong is costliest: the row is gone from every other screen until
 * restored. `archived_at` is the organization journal's SOFT_DELETE / storage
 * moment — archiving writes no date of its own.
 *
 * An alias of the generated wire type, not a hand-written mirror: the schema
 * is the truth and nothing here reshapes it.
 */
export type ArchivedStorageLocation =
  components["schemas"]["ArchivedStorageLocation"];

/**
 * What `GET /locations` actually answers with.
 *
 * Kept field-for-field against `StorageLocationSummary` in
 * `backend/app/schemas/location.py`, which the route names as its
 * `response_model`. Five fields were missing here — `short_code`, `settings`,
 * `context_schema`, `behavior_mode`, `field_definitions` — so a screen holding
 * the list could not see data the endpoint was already sending it.
 *
 * Note what is *not* here, and so is not on the wire for a list: `description`,
 * `location_details`, `location_type_id`, `created_at`, `organization_id`.
 * Those belong to the detail response.
 */
/**
 * What `GET /locations` actually answers with — the list row with the
 * precomputed counts. Taken from the schema rather than retyped: five
 * fields the hand-written copy never declared (`short_code` among them)
 * meant a screen holding the list could not see data the endpoint was
 * already sending it.
 */
export type StorageLocationSummary =
  components["schemas"]["StorageLocationSummary"];

export type StorageLocationBreadcrumb =
  components["schemas"]["StorageLocationBreadcrumb"];

export type StorageLocationNode = components["schemas"]["StorageLocationNode"];

/**
 * A category as it nests inside another response (an item's `category`).
 *
 * The categories ENDPOINTS answer with the other shape — `CategoryDTO`
 * below, which carries the list counts — so a screen reading the category
 * list reads that, not this. The name collision is the backend's own: two
 * serializations of one concept, and the OpenAPI names them both.
 */
export type Category = components["schemas"]["Category"];

/**
 * What the categories endpoints answer with (`CategoryDTO` on the wire):
 * the model plus the counts and ownership flags the list endpoint computes.
 */
export type CategoryDTO = components["schemas"]["CategoryDTO"];

export type ItemAttachment = components["schemas"]["ItemAttachmentSchema"];

/**
 * A record. Taken from the schema rather than retyped — the hand-written
 * copy was wrong where it mattered most: `quantity` and `weight` are
 * `Decimal`s on the server, so they cross the wire as strings
 * (TECHNICAL_DECISIONS §18), and declaring them `number` here blessed
 * arithmetic that concatenated (two plus three read `2.0003`). It also
 * carried `partner_id`/`partner`, which the item response model has never
 * declared, and an inline `uom` object, which the wire sends as
 * `UomInfoWithCategory`.
 */
export type Item = components["schemas"]["Item"];

/**
 * The product code to show for a record: its own, or its product's.
 *
 * One function because three screens asked the question and all three
 * asked it of `item.barcode` alone. A record keeps a code of its own only
 * when there is no catalogue entry behind it (a one-off); everything that
 * arrived through a scan carries it on the template.
 */
export function productCode(item: {
  barcode?: string | null;
  template?: { barcode?: string | null } | null;
}): string | null {
  return item.barcode || item.template?.barcode || null;
}

/**
 * The SKU an item row shows. A record has none of its own — the code lives on
 * the product, so this reads the embedded `item.template.sku`.
 */
export function itemSku(item: Item): string | null {
  return item.template?.sku || null;
}

export type ItemCreate = components["schemas"]["ItemCreate"];
export type ItemUpdate = components["schemas"]["ItemUpdate"];
export type ItemBulkUpdate = components["schemas"]["ItemBulkUpdate"];
export type ItemListResponse = components["schemas"]["ItemListResponse"];

/** Totals over the whole filtered set — `GET /items/aggregates`. */
export type ItemAggregates = components["schemas"]["ItemAggregates"];

/**
 * One row of the archive listing. Taken from the schema rather than
 * retyped: the hand-written copy was a field-for-field mirror of
 * `ArchivedItemSchema` under another name — now it is that schema.
 */
export type ArchivedItem = components["schemas"]["ArchivedItemSchema"];

export type ArchivedItemListResponse =
  components["schemas"]["ArchivedItemListResponse"];

export interface ProductLookupResult {
  name: string;
  brand?: string;
  weight?: number;
  image_url?: string;
  category_code?: string;
  sku?: string;
  is_raw_material: boolean;
  metadata: Record<string, unknown>;
}

/** A nutrition table as read off a package — the nutrition module's group. */
export interface VisionNutritionFields {
  energy_kcal?: number | null;
  proteins?: number | null;
  fat?: number | null;
  saturated_fat?: number | null;
  carbohydrates?: number | null;
  sugars?: number | null;
  fiber?: number | null;
  salt?: number | null;
  nova_group?: number | null;
  ingredients?: string | null;
}

/**
 * What a photographed label yields.
 *
 * Identity only: the nutrition figures that used to sit alongside
 * `expiry_date` here belong to the nutrition module and arrive under
 * `extra.nutrition`, present only when that module is on and the label was
 * printed for products.
 */
export interface VisionExtractResult {
  name: string | null;
  weight: string | null;
  expiry_date: string | null;
  production_date: string | null;
  brand: string | null;
  category: string | null;
  barcode: string | null;
  weight_value?: number | null;
  weight_uom?: string | null;
  volume_value?: number | null;
  volume_uom?: string | null;
  extra?: Record<string, unknown> & { nutrition?: VisionNutritionFields };
  /**
   * A product template a scan resolver recognised from the barcode the model
   * read off the label — the same chain a scanned barcode goes through.
   * Null when nothing recognised it.
   */
  resolved?: {
    name?: string | null;
    brand?: string | null;
    image_url?: string | null;
    metadata?: Record<string, unknown> | null;
  } | null;
}

export type ItemImportResponse = components["schemas"]["ItemImportResponse"];

export type ItemHistory = components["schemas"]["ItemHistorySchema"];

/**
 * The overview endpoint's response, taken from the schema rather than
 * retyped here.
 *
 * Hand-written, this declared `value_source` and
 * `excluded_other_currency_count` optional -- and the backend's response
 * model carried neither, so Pydantic dropped them and `tsc` had nothing to
 * say. The value tile could then only report "$0.00 across all items" over
 * a warehouse whose prices it had (correctly) refused to add. Derived from
 * the schema, the contract gate covers this screen.
 */
export type OverviewStats = components["schemas"]["OverviewStats"];
export type LowStockProduct = components["schemas"]["LowStockProduct"];

export type StorageStats = components["schemas"]["StorageStats"];
export type CategoryStats = components["schemas"]["CategoryStats"];
export type ExpiryForecast = components["schemas"]["ExpiryForecast"];
/**
 * What needs attention, from the one endpoint both screens read.
 *
 * An alias of the generated wire type: the schema is the truth, and a
 * retyped copy here is how the heading and the health card came to count
 * the same concept two ways in the first place.
 */
export type AttentionCounts = components["schemas"]["AttentionCounts"];

// Label System Types
/**
 * One label pool row. Taken from the schema rather than retyped: the
 * hand-written copy was a field-for-field mirror of `LabelPoolResponse`
 * under another name — now it is that schema.
 */
export type LabelPool = components["schemas"]["LabelPoolResponse"];

export type LabelPoolListResponse =
  components["schemas"]["LabelPoolListResponse"];

/**
 * The product a scan resolved to, as the scan providers assemble it.
 *
 * `metadata` carries whatever the item or the Open Food Facts lookup put
 * under `meta_data` — nutrition values, Nutri-Score, ingredient text. It was
 * missing from this type while both providers had always sent it, so anything
 * reading it through the declared shape was reading a field that, on paper,
 * did not exist.
 */
export interface ScannedTemplate {
  id?: string | null;
  name: string;
  brand?: string | null;
  sku?: string | null;
  uom_id?: string | null;
  category_id?: string | null;
  location_id?: string | null;
  weight_value?: number | null;
  weight_uom_id?: string | null;
  volume_value?: number | null;
  volume_uom_id?: string | null;
  image_url?: string | null;
  metadata?: Record<string, unknown> | null;
}

/**
 * The scan endpoint's answer, as the contract declares it: the payload
 * fields the server builds by hand are typed `dict` on the backend, so the
 * schema keeps them open. Screens read the response through
 * {@link LabelScanView}, which states what the server actually puts in
 * those dicts — one assertion where the response arrives, not a copy of
 * the schema under its name.
 */
export type LabelScanResponse = components["schemas"]["LabelScanResponse"];

/**
 * What the server actually builds into `LabelScanResponse`'s open payload
 * fields. This is a working view over the wire shape, not a rival of it:
 * the backend assembles `item`, `location`, `stock_summary` and
 * `document` by hand and declares them `dict`, so the narrow fields live
 * here under a UI-only name while the wire type stays the schema's.
 */
export interface LabelScanView {
  status:
    | "unassigned"
    | "assigned"
    | "storage_context"
    | "archived"
    | "product_stock"
    | "document";
  label_code: string;
  /**
   * Catalog key for the line under the status, and the values it needs.
   *
   * The server used to send the sentence itself, in English, for every reader
   * — see `LabelScanResponse` in `app/schemas/label_pool.py`.
   */
  message_key?: string | null;
  message_params?: Record<string, string> | null;
  action:
    | "show_quick_add"
    | "show_quick_actions"
    | "set_storage_context"
    | "show_archived_info"
    | "show_stock_actions"
    | "open_document";
  item?: Item;
  location?: {
    id: string;
    name: string;
    icon: string;
    type_code?: string;
  };
  stock_summary?: {
    total_quantity: number;
    unit: string;
    locations?: string[];
    template?: ScannedTemplate;
    /** How the product leaves a shelf: oldest best-before or oldest record first. */
    removal_strategy?: "FIFO" | "FEFO";
    items: {
      id: string;
      expiry_date: string | null;
      opened_at?: string | null;
      location: string;
      location_id?: string;
      /** The shelf's whole path, root first ("Warehouse → Rack 4 → Shelf 2"). */
      location_path?: string;
      location_code?: string | null;
      lot?: string | null;
      created_at?: string;
      quantity: number;
      reserved_quantity?: number;
      available_quantity?: number;
    }[];
  };
  quick_actions?: string[];
  context_tag?: string | null;
  /** A scanned document printout: open this document. */
  document?: {
    id: string;
    number: string;
    status: string;
    type: string;
  } | null;
  /** How to open it: continuation for an in-progress document, the floor
   *  flow (receiving/picking) for a CONFIRMED one, preview otherwise. */
  document_mode?: "continue" | "execute" | "preview" | null;
}

export type LabelAssignRequest = components["schemas"]["LabelAssignRequest"];
