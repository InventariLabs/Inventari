import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";
// Stock-take types.

export type StockTakeStatus = components["schemas"]["StockTakeStatus"];

/** One pass of counting over one row — the first, the recount, the next. */
/** One counting pass of an item — the element type the contract gives `counts`. */
export type StockTakeCount = NonNullable<StockTakeItem["counts"]>[number];

export type StockTakeItem = components["schemas"]["StockTakeItemWithDetails"];

/** A location the count covers, with its whole path. */
export type CountedLocation = components["schemas"]["CountedLocation"];

/** A location the counter closed, and who closed it. */
export type ClosedLocation = components["schemas"]["ClosedLocation"];

/** The answer to closing a location: how many rows it counted as 0. */
export type ShelfClosed = components["schemas"]["ShelfClosed"];

/** A stock take with its items — what the detail read answers. */
export type StockTake = components["schemas"]["StockTakeWithDetails"];

/** A stock take as the list answers it: no items, no storage type. */
export type StockTakeSummary = components["schemas"]["StockTakeResponse"];

export type StockTakeCreate = components["schemas"]["StockTakeCreate"];

/** What a caller sends: the counting options it leaves out are the server's defaults. */
export type StockTakeCreateInput = WithServerDefaults<
  StockTakeCreate,
  "blind_mode" | "require_full_count"
>;

export type StockTakeUpdate = components["schemas"]["StockTakeUpdate"];

export type StockTakeReport = components["schemas"]["StockTakeReport"];

/** When a location was last counted, and the count open on it now. */
export type LocationCountState = components["schemas"]["LocationCountState"];

export type StockTakeListResponse =
  components["schemas"]["PaginatedResponse_StockTakeResponse_"];
