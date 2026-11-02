/** Which sheet column feeds which partner field.
 *
 * The keys are what the import endpoint reads; the empty string means skip.
 * `suggestPartnerMapping` fills them from the header row, in English and
 * Polish, so a sheet kept the way a small company keeps one lands without
 * a click per column. */
import type { ImportMapping } from "@/components/import/types";

export const PARTNER_IMPORT_FIELDS = [
  "name",
  "code",
  "type",
  "tax_id",
  "email",
  "phone",
  "website",
  "contact_person",
  "street",
  "city",
  "postal_code",
  "country",
  "notes",
] as const;

/** Header shapes per field, tried in this order. Exact words come before
 *  substrings so "Postal code" is the postal code, not the partner code. */
const RULES: {
  field: (typeof PARTNER_IMPORT_FIELDS)[number];
  exact?: string[];
  includes?: string[];
}[] = [
  { field: "name", exact: ["name", "nazwa", "partner", "company", "firma"] },
  { field: "postal_code", includes: ["postal", "zip", "kod pocztowy"] },
  { field: "tax_id", includes: ["tax", "vat", "nip"] },
  { field: "code", exact: ["code", "kod", "partner code", "kod partnera"] },
  { field: "type", exact: ["type", "typ", "role", "rola"] },
  { field: "email", includes: ["email", "e-mail", "mail"] },
  { field: "phone", includes: ["phone", "telefon", "tel"] },
  { field: "website", includes: ["website", "www", "web", "strona"] },
  { field: "contact_person", includes: ["contact", "osoba", "kontakt"] },
  { field: "street", includes: ["street", "ulica", "address", "adres"] },
  { field: "city", exact: ["city", "miasto", "town"] },
  { field: "country", exact: ["country", "kraj"] },
  { field: "notes", includes: ["note", "uwagi", "notatki", "comment"] },
];

function fieldFor(header: string): string | null {
  const h = header.trim().toLowerCase();
  const rule = RULES.find(
    (r) => r.exact?.includes(h) || r.includes?.some((p) => h.includes(p)),
  );
  return rule?.field ?? null;
}

export function suggestPartnerMapping(headers: string[]): ImportMapping {
  const mapping: ImportMapping = Object.fromEntries(
    PARTNER_IMPORT_FIELDS.map((key) => [key, ""]),
  );
  headers.forEach((header) => {
    const field = fieldFor(header);
    if (field && !mapping[field]) mapping[field] = header;
  });
  return mapping;
}
