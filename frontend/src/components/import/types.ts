import type { components } from "@/types/api-generated";

/** The shape every spreadsheet import shares.
 *
 * The server reports how many rows it read, how many it kept and, for the
 * first few refused, the row number and the reason — products and partners
 * alike. An entity may add what its import founded on the way. */
export interface ImportRowError {
  row: number;
  error: string;
}

export interface ImportOutcome {
  total: number;
  imported: number;
  failed: number;
  errors: ImportRowError[];
}

/** How far a background import has got: rows read of rows in the sheet. */
export interface ImportProgress {
  processed: number;
  total: number;
}

/** Which sheet column feeds which field; the empty string means skip. */
export type ImportMapping = Record<string, string>;

/**
 * The product import's answer as the wizard reads it: the schema's counts
 * with the errors list narrowed to the rows the server actually builds —
 * the narrowing itself happens once, in `itemsApi.importItems`.
 */
export type ItemImportOutcome = components["schemas"]["ItemImportResponse"] & {
  errors: ImportRowError[];
};

/** The partner import's answer, narrowed the same way in `partnersApi`. */
export type PartnerImportOutcome =
  components["schemas"]["PartnerImportResponse"] & {
    errors: ImportRowError[];
  };

/** A field the mapping step offers, with its label already translated. */
export interface MappingField {
  key: string;
  label: string;
  required?: boolean;
}

/** What the analyze step tells the mapping step about the uploaded sheet.
 *
 * The generated contract itself, not a second spelling of it: headers alone
 * were not enough — a mapping chosen against column names and nothing else
 * cannot be checked by the person choosing it. */
export type SheetAnalysis = components["schemas"]["SheetAnalysisResponse"];

/** One row of the source, as the analyze step read it: column name → cell. */
export type ImportPreviewRow = components["schemas"]["ImportPreviewRow"];
