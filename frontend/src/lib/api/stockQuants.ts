/**
 * What lies where — GET /api/v1/stock-quants.
 *
 * The authoritative stock record, as opposed to the `Item.quantity` cache
 * the product list shows. Read-only: quants move through receipts, issues
 * and counts, never by editing a number here.
 */
import { api } from "./client";
import type { components } from "@/types/api-generated";

export type StockQuantRow = components["schemas"]["StockQuantRowDTO"];
export type StockQuantsPage =
  components["schemas"]["PaginatedResponse_StockQuantRowDTO_"];

export interface StockQuantFilters {
  product_template_id?: string;
  /** Answers for this location and everything below it. */
  location_id?: string;
  lot_id?: string;
  /** Shelves drained to zero — the only record of where a product used to be. */
  include_empty?: boolean;
  /**
   * What the reader typed: matched against the product (name, brand, barcode,
   * SKU) and the batch name. Server-side, because this list is paged — a
   * filter over the rows already loaded would answer "not on the first page"
   * to a question about the whole warehouse.
   */
  search?: string;
  limit?: number;
  offset?: number;
}

export const stockQuantsApi = {
  list: async (filters: StockQuantFilters = {}): Promise<StockQuantsPage> => {
    const params: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params[key] = value;
    }
    const response = await api.get<StockQuantsPage>("/stock-quants", {
      params,
    });
    return response.data;
  },
};
