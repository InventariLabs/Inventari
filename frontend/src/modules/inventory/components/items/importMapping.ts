/** Which sheet column feeds which product field.
 *
 * The keys are what the import endpoint reads; the empty string means
 * "skip / default". `suggestMapping` fills them from the header row so a
 * sheet this app exported itself — and the exports of the tools people move
 * from (Odoo, Sortly, inFlow, Zoho, Katana, BoxHero, Homebox) — import
 * without a single click. */
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
  sublocation: "",
  category: "",
  purchase_price: "",
  label_code: "",
  sku: "",
  description: "",
  min_quantity: "",
};

/** Header shapes per field, tried in this order. Exact words come before
 *  substrings so "Purchase price per unit (USD)" is the price, not the unit. */
const RULES: {
  field: string;
  exact?: string[];
  startsWith?: string[];
  includes?: string[];
  /** A header starting so is not this field, whatever it includes. */
  not?: string;
}[] = [
  {
    field: "name",
    exact: [
      "name",
      "nazwa",
      "product name",
      "item name",
      "entry name",
      "productname",
      "product",
      "material name",
      "product name / material name",
      "artikelname",
    ],
  },
  // Before barcode: both are codes, and only this one identifies a product
  // the app already has.
  { field: "label_code", exact: ["label code", "kod etykiety"] },
  {
    field: "sku",
    exact: ["sku", "internal reference", "variant code / sku", "variant code"],
  },
  { field: "description", exact: ["description"] },
  {
    field: "min_quantity",
    exact: ["stock alert", "min level", "reorder level"],
  },
  {
    field: "unit",
    exact: [
      "unit",
      "uom",
      "jednostka",
      "unit of measure",
      "unitofmeasure",
      "usage unit",
    ],
  },
  {
    field: "serial_number",
    exact: ["serial number", "serial", "numer seryjny", "serial_number"],
  },
  {
    field: "barcode",
    exact: ["barcode", "kod", "kod kreskowy", "barcode/qr-1", "ean"],
  },
  { field: "brand", exact: ["brand", "marka", "manufacturer"] },
  {
    field: "purchase_price",
    exact: [
      "cost",
      "purchase rate",
      "default purchase price",
      "purchase_price",
    ],
    startsWith: ["purchase price"],
  },
  {
    field: "quantity",
    exact: ["amount", "ilość", "qty", "stock on hand"],
    includes: ["quantity"],
    // Odoo's reserved stock is part of what is on hand, not a second count.
    not: "reserved",
  },
  { field: "expiry_date", exact: ["best_before_date"], includes: ["expiry"] },
  { field: "freeze_date", includes: ["freeze", "zamroż"] },
  { field: "sublocation", exact: ["sublocation"] },
  {
    field: "location",
    exact: ["location", "folder path", "warehouse name"],
    includes: ["storage", "lokalizacja"],
  },
  {
    field: "category",
    exact: ["product_group"],
    includes: ["category", "kategoria"],
  },
];

/** Headers that feed a field only when no other column does: a bare "Price"
 *  is the selling price wherever a "Cost" stands beside it, and "Notes"
 *  describe a product only when nothing else does. */
const FALLBACKS: { field: string; exact: string[] }[] = [
  { field: "purchase_price", exact: ["price", "cena"] },
  { field: "description", exact: ["notes"] },
];

/** A header as the rules read it; Homebox heads every column "HB.". */
const plain = (header: string) =>
  header.trim().toLowerCase().replace(/^hb\./, "");

/** The mapping keys of the columns holding the quantity at one location,
 *  headed "Qty(<location>)" the way BoxHero writes them. */
export function stockColumns(headers: string[]): ImportMapping {
  const columns: ImportMapping = {};
  headers.forEach((header) => {
    const location = /^qty\s*\((.+)\)$/i.exec(header.trim())?.[1].trim();
    if (location) columns[`stock_at:${location}`] = header;
  });
  return columns;
}

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
  const labelled = byLabel.get(header.trim().toLowerCase());
  if (labelled) return labelled;
  const h = plain(header);
  const rule = RULES.find(
    (r) =>
      !(r.not && h.startsWith(r.not)) &&
      (r.exact?.includes(h) ||
        r.startsWith?.some((p) => h.startsWith(p)) ||
        r.includes?.some((p) => h.includes(p))),
  );
  return rule?.field ?? null;
}

/** The mapping key of a product field a location sets — what the import
 *  endpoint reads as one of that location's fields, not a system column. */
export const locationFieldKey = (key: string) => `field:${key}`;

/**
 * A header is suggested for the field whose label the dialog shows in the
 * reader's language (`fieldLabels`: field key → label) or, failing that,
 * for one of the shapes in RULES. A sheet with a quantity column per
 * location is read by those columns instead of a quantity and a location.
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
  FALLBACKS.forEach(({ field, exact }) => {
    const header = headers.find((h) => exact.includes(plain(h)));
    if (header && !mapping[field]) mapping[field] = header;
  });
  const perLocation = stockColumns(headers);
  if (Object.keys(perLocation).length > 0) {
    Object.assign(mapping, perLocation, { quantity: "", location: "" });
  }
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
