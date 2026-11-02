/**
 * What the replenish door asks the engine for.
 *
 * The dashboard's button and the modal it opens have to ask the same
 * question, or the door and its content are two different computations:
 * the engine returns every source it knows unless it is told otherwise,
 * and a door opening on a *narrower* question than its content is how a
 * "replenish shortages" button once opened a screenful of products that
 * had expired. The reverse — a door still open after the run's proposals
 * are on a list — has the same root, so both call sites read this one
 * value and the same query key hangs off it.
 */
export const REPLENISH_SUGGESTION_SOURCES = {
  include_low_stock: true,
  include_frequent: false,
  include_expiring: false,
} as const;
