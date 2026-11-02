import type { DocumentDiscrepancyCode } from "@/modules/warehouse/types";

export const DOCUMENT_DISCREPANCY_CODES: DocumentDiscrepancyCode[] = [
  "SHORTAGE",
  "DAMAGE",
  "QUALITY_HOLD",
  "COUNT_VARIANCE",
  "SURPLUS",
  "OTHER",
];

/** The codes under which a receipt may hold part of what it received back.
 *  The server refuses a held quantity under any other code. */
export const DOCUMENT_HELD_CODES: DocumentDiscrepancyCode[] = [
  "DAMAGE",
  "QUALITY_HOLD",
];

/** The reasons that can explain a picking line coming up short. A surplus
 *  or a count variance describes a receipt or a stock take, not a shelf
 *  that held less than the pick asked for. */
export const PICK_SHORTAGE_CODES: DocumentDiscrepancyCode[] = [
  "SHORTAGE",
  "DAMAGE",
  "QUALITY_HOLD",
  "OTHER",
];
