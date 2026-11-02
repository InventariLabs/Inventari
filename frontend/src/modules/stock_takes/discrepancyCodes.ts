import type { components } from "@/types/api-generated";

/**
 * Why a counted quantity differs from what the system held.
 *
 * The backend owns the list (`stock_takes/models.py`); this is the generated
 * enum, in the order the picker offers it. The order is deliberate: the
 * reasons a counter meets on the shelf come first, the ones that mean "the
 * records were wrong" after them, and the escape hatch last.
 */
export type StockTakeDiscrepancyCode =
  components["schemas"]["StockTakeDiscrepancyCode"];

export const DISCREPANCY_REASON_CODES: StockTakeDiscrepancyCode[] = [
  "DAMAGE",
  "EXPIRED",
  "LOSS",
  "WRONG_LOCATION",
  "WRONG_UNIT",
  "MISCOUNT",
  "SYSTEM_ERROR",
  "OTHER",
];
