import type { StorageLocationSummary } from "@/types";

/**
 * A storage location in the shape `GET /locations` answers with.
 *
 * Five test files each grew their own factory, and each built a
 * `StorageLocation` — the detail shape, carrying `description`,
 * `location_details`, `created_at` and friends that the list endpoint does not
 * send. Fixtures richer than the wire let a component read a field in a test
 * that would be `undefined` in the product, which is how one screen came to
 * show a description nobody could ever see.
 *
 * Keep this aligned with `StorageLocationSummary` in
 * `backend/app/schemas/location.py`.
 */
export const makeStorageSummary = (
  overrides: Partial<StorageLocationSummary> = {},
): StorageLocationSummary => ({
  id: "s1",
  name: "Main Site",
  parent_id: null,
  short_code: null,
  settings: null,
  location_type: null,
  context_schema: [],
  behavior_mode: "STOCK",
  field_definitions: [],
  inherited_context_schema: [],
  inherited_field_definitions: [],
  context_tag: null,
  usage: "internal",
  items_count: 0,
  subtree_items_count: 0,
  total_items_count: 0,
  total_subtree_items_count: 0,
  direct_children_count: 0,
  listed_children_count: 0,
  expiring_soon_count: 0,
  full_path: null,
  is_leaf: true,
  ...overrides,
});

type LocationField = StorageLocationSummary["field_definitions"][number];

/** A product field a location sets, as the storages listing sends it. */
export const makeLocationField = (
  key: string,
  extra: Partial<LocationField> = {},
): LocationField => ({
  key,
  type: "text",
  required: false,
  is_system: false,
  visible: true,
  ...extra,
});
