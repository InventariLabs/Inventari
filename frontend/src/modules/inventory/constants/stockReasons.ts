/**
 * The vocabulary for "where did it go".
 *
 * Two dialogs in this module used to ask that question with two lists of their
 * own — Used / Expired / Damaged / Lost / Retired / Test data / Other on the
 * one deleting a record, Used / Disposed / Damaged / Expired / Other on the one
 * taking stock down — and drew the words from two separate key families, so
 * "Used" was written twice and could drift apart.
 *
 * The two questions are genuinely different: a record goes away for reasons a
 * quantity never does (it was somebody's test data), and stock goes down for
 * reasons a record does not (it was thrown out). So they take different
 * subsets — of one vocabulary, spelled once.
 */
export const STOCK_REASONS = {
  USED: "USED",
  DISPOSED: "DISPOSED",
  EXPIRED: "EXPIRED",
  DAMAGED: "DAMAGED",
  LOST: "LOST",
  RETIRED: "RETIRED",
  TEST_DATA: "TEST_DATA",
  OTHER: "OTHER",
} as const;

export type StockReason = (typeof STOCK_REASONS)[keyof typeof STOCK_REASONS];

/** The i18n key for one reason — one family, so one wording. */
export const reasonLabelKey = (reason: StockReason): string =>
  `items:deletionReasons.${reason}`;

/** Why a record is being deleted. */
export const DELETION_REASONS: readonly StockReason[] = [
  STOCK_REASONS.USED,
  STOCK_REASONS.EXPIRED,
  STOCK_REASONS.DAMAGED,
  STOCK_REASONS.LOST,
  STOCK_REASONS.RETIRED,
  STOCK_REASONS.TEST_DATA,
  STOCK_REASONS.OTHER,
];

/** Why a quantity went down. */
export const CONSUMPTION_REASONS: readonly StockReason[] = [
  STOCK_REASONS.USED,
  STOCK_REASONS.DISPOSED,
  STOCK_REASONS.DAMAGED,
  STOCK_REASONS.EXPIRED,
  STOCK_REASONS.OTHER,
];

/** The reasons that mean the goods were thrown out, not consumed. The
 *  discard endpoint files them under DISPOSED, which is what separates a
 *  disposal from a use in the ledger, the journal and the waste report —
 *  routing them through consume made every bin read as 0.00 wasted. */
const DISPOSAL_REASONS: readonly StockReason[] = [
  STOCK_REASONS.DISPOSED,
  STOCK_REASONS.DAMAGED,
  STOCK_REASONS.EXPIRED,
];

export const isDisposalReason = (reason: string): boolean =>
  DISPOSAL_REASONS.includes(reason as StockReason);
