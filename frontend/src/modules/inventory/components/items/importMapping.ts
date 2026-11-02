/** Which sheet column feeds which product field.
 *
 * The keys are what the import endpoint reads; the empty string means
 * "skip / default". `suggestMapping` fills them from the header row so a
 * sheet this app exported itself round-trips without a single click — every
 * header `export_items_to_xlsx` writes has a rule here. */
export type ImportMapping = Record<string, string>;

const EMPTY_MAPPING: ImportMapping = {
  name: "",
  brand: "",
  quantity: "",
  unit: "",
  expiry_date: "",
  freeze_date: "",
  barcode: "",
  serial_number: "",
  location: "",
  category: "",
  purchase_price: "",
  label_code: "",
};

const GROCY_MAPPING: Record<string, string> = {
  name: "name",
  quantity: "amount",
  expiry_date: "best_before_date",
  location: "location",
  category: "product_group",
  barcode: "barcode",
  purchase_price: "price",
};

/** Header shapes per field, tried in this order. Exact words come before
 *  substrings so "Purchase price per unit (USD)" is the price, not the unit. */
const RULES: {
  field: string;
  exact?: string[];
  startsWith?: string[];
  includes?: string[];
}[] = [
  { field: "name", exact: ["name", "nazwa", "product name"] },
  // Before barcode: both are codes, and only this one identifies a product
  // the app already has.
  { field: "label_code", exact: ["label code", "kod etykiety"] },
  { field: "unit", exact: ["unit", "uom", "jednostka"] },
  {
    field: "serial_number",
    exact: ["serial number", "serial", "numer seryjny"],
  },
  { field: "barcode", exact: ["barcode", "kod", "kod kreskowy"] },
  { field: "brand", exact: ["brand", "marka"] },
  {
    field: "purchase_price",
    exact: ["price", "cena"],
    startsWith: ["purchase price"],
  },
  { field: "quantity", exact: ["amount", "ilość"], includes: ["quantity"] },
  { field: "expiry_date", exact: ["best_before_date"], includes: ["expiry"] },
  { field: "freeze_date", includes: ["freeze", "zamroż"] },
  {
    field: "location",
    exact: ["location"],
    includes: ["storage", "lokalizacja"],
  },
  {
    field: "category",
    exact: ["product_group"],
    includes: ["category", "kategoria"],
  },
];

/** The words the dialog itself labels each field with, in the reader's
 *  language, keyed by the lower-cased label. A hint such as "(szt., kg, …)"
 *  is not part of the name a sheet would carry, so the bare name counts too. */
function labelIndex(labels: Record<string, string>): Map<string, string> {
  const index = new Map<string, string>();
  Object.entries(labels).forEach(([field, label]) => {
    const full = label.trim().toLowerCase();
    index.set(full, field);
    index.set(full.replace(/\s*\(.*\)\s*$/, ""), field);
  });
  return index;
}

function fieldFor(
  header: string,
  byLabel: Map<string, string> = new Map(),
): string | null {
  const h = header.trim().toLowerCase();
  const labelled = byLabel.get(h);
  if (labelled) return labelled;
  const rule = RULES.find(
    (r) =>
      r.exact?.includes(h) ||
      r.startsWith?.some((p) => h.startsWith(p)) ||
      r.includes?.some((p) => h.includes(p)),
  );
  return rule?.field ?? null;
}

/** The mapping key of a product field a location sets — what the import
 *  endpoint reads as one of that location's fields, not a system column. */
export const locationFieldKey = (key: string) => `field:${key}`;

/**
 * A header is suggested for the field whose label the dialog shows in the
 * reader's language (`fieldLabels`: field key → label) or, failing that,
 * for one of the English or Polish shapes in RULES.
 *
 * A location's product field is suggested for the header carrying its label,
 * or the "Custom: <key>" header the export writes for its value, so an
 * exported sheet round-trips its fields too.
 */
export function suggestMapping(
  headers: string[],
  locationFields: { key: string; label?: string | null }[] = [],
  fieldLabels: Record<string, string> = {},
): ImportMapping {
  const mapping = { ...EMPTY_MAPPING };
  const byLabel = labelIndex(fieldLabels);
  headers.forEach((header) => {
    const field = fieldFor(header, byLabel);
    if (field && !mapping[field]) mapping[field] = header;
  });
  locationFields.forEach(({ key, label }) => {
    const names = [
      (label ?? key).toLowerCase(),
      `custom: ${key}`.toLowerCase(),
    ];
    const header = headers.find((h) => names.includes(h.trim().toLowerCase()));
    if (header) mapping[locationFieldKey(key)] = header;
  });
  return mapping;
}

export function applyGrocyPreset(
  headers: string[],
  mapping: ImportMapping,
): ImportMapping {
  const next = { ...mapping };
  Object.entries(GROCY_MAPPING).forEach(([field, grocyHeader]) => {
    const actual = headers.find(
      (h) => h.toLowerCase() === grocyHeader.toLowerCase(),
    );
    if (actual) next[field] = actual;
  });
  return next;
}
