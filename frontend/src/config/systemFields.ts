import type { FieldDefinition } from "@/types";

/**
 * System fields configuration.
 * These fields map directly to the Item model properties but can be controlled dynamically via field_definitions.
 * If a field is present in field_definitions, its visibility and label can be overridden.
 * If not present, it falls back to these defaults (usually hidden or default visible based on logic).
 */
/**
 * The context tags the food vertical speaks: 'food' is the word storage
 * creation infers (services/storage_hierarchy_service), while the seeded
 * food categories carry 'cold_storage' and 'dry_goods'. A field or panel gated
 * on one word alone vanishes the moment a seeded category is picked.
 */
export const FOOD_CONTEXTS = ["food", "cold_storage", "dry_goods"];

export const SYSTEM_FIELDS: Record<string, Partial<FieldDefinition>> = {
  name: {
    key: "name",
    label: "itemName",
    type: "text",
    required: true,
    visible: true,
    is_custom: false,
    contexts: null,
  },
  quantity: {
    key: "quantity",
    label: "itemQuantity",
    type: "number",
    required: true,
    visible: true,
    is_custom: false,
    contexts: null,
  },
  unit: {
    key: "unit",
    label: "itemUnit",
    type: "select",
    required: false,
    visible: true,
    is_custom: false,
    contexts: null,
    options: [
      "pcs",
      "kg",
      "g",
      "l",
      "ml",
      "pack",
      "can",
      "bottle",
      "box",
      "bag",
    ],
  },
  brand: {
    key: "brand",
    label: "itemBrand",
    type: "text",
    required: false,
    visible: true,
    is_custom: false,
    contexts: null,
  },
  description: {
    key: "description",
    label: "itemDescription",
    type: "textarea",
    required: false,
    visible: true,
    is_custom: false,
    contexts: null,
    placeholder: "placeholders.description",
  },
  category_id: {
    key: "category_id",
    label: "itemCategory",
    type: "select",
    required: false,
    // Visible by default: a product form that draws the picker owes the
    // payload the same field. This is the single source both the renderer
    // and buildSubmissionPayload read — a category's own field_definitions
    // can still override it, and only that override hides it again.
    visible: true,
    is_custom: false,
    contexts: null,
  },
  expiry_date: {
    key: "expiry_date",
    label: "itemExpiryDate",
    type: "date",
    required: false,
    visible: true,
    is_custom: false,
    // Gated on every food tag, not one: a field gated on one word alone
    // vanished the moment a seeded category was picked — the expiry date
    // disappeared together with the value typed into it.
    contexts: FOOD_CONTEXTS,
    // Shelf life is thought of as an interval, not a date on a calendar.
    // Only jumps that land outside the open month grid — a shortcut that saves
    // no navigation is a button competing with the calendar under it.
    date_presets: ["plus6Months", "plus1Year", "plus3Years"],
  },
  freeze_date: {
    key: "freeze_date",
    label: "table.freezeDate",
    type: "date",
    required: false,
    visible: true,
    is_custom: false,
    contexts: FOOD_CONTEXTS,
    // No shortcuts: something is frozen today or in the last few days, and
    // every one of those dates is already on the grid the panel opens on.
    date_presets: [],
  },
  shelf_location: {
    key: "shelf_location",
    label: "itemShelfLocation",
    type: "text",
    required: false,
    visible: true,
    is_custom: false,
    contexts: null,
    placeholder: "placeholders.shelf_location",
  },
  weight: {
    key: "weight",
    label: "itemWeightNet",
    type: "number",
    required: false,
    visible: true,
    is_custom: false,
    contexts: FOOD_CONTEXTS,
    placeholder: "placeholders.weight",
  },
  purchase_price: {
    key: "purchase_price",
    label: "fields.purchase_price",
    type: "number",
    required: false,
    visible: true,
    is_custom: false,
    contexts: null,
    placeholder: "placeholders.purchase_price",
  },
  barcode: {
    key: "barcode",
    label: "fields.barcode",
    type: "text",
    required: false,
    // Visible by default: the code is what a receiving or picking scan finds
    // a product by, and this form is the one place a worker can give it one.
    // A location that lists the fields it tracks still decides for itself.
    visible: true,
    is_custom: false,
    contexts: null,
    placeholder: "placeholders.barcode",
  },
  sku: {
    key: "sku",
    label: "fields.sku",
    type: "text",
    required: false,
    // The product's own stock-keeping number. Typed here, or numbered by the
    // organization's scheme when left empty; it lives on the product, so a
    // change reaches every record of it.
    visible: true,
    is_custom: false,
    contexts: null,
    placeholder: "placeholders.sku",
  },
  serial_number: {
    key: "serial_number",
    label: "fields.serial_number",
    type: "text",
    required: false,
    visible: true,
    is_custom: false,
    // One physical, uniquely numbered unit: equipment. A jar of ketchup has
    // none, so a food category (or a food scan) takes the field away.
    contexts: ["equipment"],
    placeholder: "placeholders.serial_number",
  },
};
