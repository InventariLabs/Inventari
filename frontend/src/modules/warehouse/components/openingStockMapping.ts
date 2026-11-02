/** Which sheet column feeds which line of the opening receipt.
 *
 * The keys are what the document import endpoint reads; the empty string
 * means skip. A stock sheet kept outside this app carries the company's own
 * codes and names more often than barcodes, in Polish as often as in
 * English, so the header rules speak both. */
import type { ImportMapping } from "@/components/import/types";

export const OPENING_STOCK_FIELDS = [
  "name",
  "sku",
  "barcode",
  "quantity",
  "uom_symbol",
  "unit_price",
  "batch_number",
  "expiry_date",
] as const;

/** Header shapes per field, tried in this order. The barcode rule comes
 *  before the partner-style "code" rules so "Kod kreskowy" is a barcode. */
const RULES: {
  field: (typeof OPENING_STOCK_FIELDS)[number];
  exact?: string[];
  includes?: string[];
}[] = [
  { field: "barcode", includes: ["barcode", "ean", "kreskowy", "gtin"] },
  { field: "name", exact: ["name", "nazwa", "product", "produkt", "towar"] },
  { field: "sku", exact: ["sku", "code", "kod", "index", "indeks", "symbol"] },
  { field: "unit_price", includes: ["price", "cena", "cost", "koszt"] },
  {
    field: "quantity",
    includes: ["quantity", "qty", "ilość", "ilosc", "stan"],
  },
  { field: "uom_symbol", exact: ["unit", "uom", "jm", "jednostka", "j.m."] },
  { field: "batch_number", includes: ["batch", "lot", "partia", "seria"] },
  {
    field: "expiry_date",
    includes: ["expir", "ważno", "wazno", "best before"],
  },
];

function fieldFor(header: string): string | null {
  const h = header.trim().toLowerCase();
  const rule = RULES.find(
    (r) => r.exact?.includes(h) || r.includes?.some((p) => h.includes(p)),
  );
  return rule?.field ?? null;
}

export function suggestOpeningStockMapping(headers: string[]): ImportMapping {
  const mapping: ImportMapping = Object.fromEntries(
    OPENING_STOCK_FIELDS.map((key) => [key, ""]),
  );
  headers.forEach((header) => {
    const field = fieldFor(header);
    if (field && !mapping[field]) mapping[field] = header;
  });
  return mapping;
}
