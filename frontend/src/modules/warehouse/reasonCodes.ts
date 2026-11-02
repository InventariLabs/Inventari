import type { components } from "@/types/api-generated";

/**
 * Why a correction is raised, why goods come back and why they are written off.
 *
 * The backend owns both lists (`reason_codes.py`); these are the generated
 * enums, listed in the order the pickers offer them. A code is what reports
 * count; the note beside it says what the code cannot, and stops being
 * optional when the code is "Other" — the shared `ReasonCodeField` owns that
 * rule, for every list that has one.
 */
export type CorrectionReasonCode =
  components["schemas"]["CorrectionReasonCode"];
export type ReturnReasonCode = components["schemas"]["ReturnReasonCode"];
export type ScrapReasonCode = components["schemas"]["ScrapReasonCode"];

export const CORRECTION_REASON_CODES: CorrectionReasonCode[] = [
  "WRONG_QUANTITY",
  "WRONG_PRODUCT",
  "WRONG_PRICE",
  "DATA_ENTRY_ERROR",
  "OTHER",
];

export const RETURN_REASON_CODES: ReturnReasonCode[] = [
  "DAMAGED",
  "WRONG_ITEM",
  "QUALITY",
  "NOT_NEEDED",
  "OTHER",
];

export const SCRAP_REASON_CODES: ScrapReasonCode[] = [
  "DAMAGED",
  "EXPIRED",
  "QUALITY",
  "OTHER",
];
