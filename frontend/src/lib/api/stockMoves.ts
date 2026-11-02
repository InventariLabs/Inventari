/**
 * The organization's movement ledger — GET /api/v1/stock-moves.
 *
 * Read-only: movements are recorded by the services that move stock, never
 * posted from here. The types come from the generated schema rather than
 * being written twice (AGENTS.md: `api-generated.ts` is the contract).
 */
import axios from "axios";
import { api } from "./client";
import type { components } from "@/types/api-generated";

export type StockMoveRow = components["schemas"]["StockMoveRowDTO"];
export type StockMovesPage =
  components["schemas"]["KeysetPaginatedResponse_StockMoveRowDTO_"];

/** Which way the goods went, read off the pair of locations. */
export type StockMoveDirection = "in" | "out" | "internal";

export interface StockMoveFilters {
  product_template_id?: string;
  /** Answers for this location and everything below it. */
  location_id?: string;
  lot_id?: string;
  reference_type?: string;
  reference_id?: string;
  user_id?: string;
  direction?: StockMoveDirection;
  /** ISO instant — when the goods moved, not when the row was written. */
  since?: string;
  until?: string;
  /**
   * Leave out the movements of products whose every record belongs to a
   * vertical module — the general lists' rule, for a screen that reads the
   * ledger beside them.
   */
  exclude_module_contexts?: boolean;
  limit?: number;
  /**
   * Where the previous page ended — its `next_cursor`. A page is reached from
   * the one before it, so the cost of a page does not grow with its depth.
   */
  cursor?: string;
}

function toParams(filters: StockMoveFilters): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params[key] = value;
  }
  return params;
}

export const stockMovesApi = {
  list: async (filters: StockMoveFilters = {}): Promise<StockMovesPage> => {
    const response = await api.get<StockMovesPage>("/stock-moves", {
      params: toParams(filters),
    });
    return response.data;
  },

  /**
   * The same question, as a spreadsheet. Paging is left out on purpose: the
   * file carries every matching row, or the request is refused with the
   * count and a suggestion to narrow it.
   */
  exportXlsx: async (
    filters: Omit<StockMoveFilters, "limit" | "cursor"> = {},
  ): Promise<Blob> => {
    try {
      const response = await api.get("/stock-moves/export/xlsx", {
        params: {
          ...toParams(filters),
          // The screens print timestamps in the browser's zone; without
          // this the sheet would disagree with the rows just read.
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        responseType: "blob",
      });
      return response.data as Blob;
    } catch (error) {
      // Asking for a blob means the error body arrives as one too, and
      // every reader of an axios error expects JSON. Unwrapped here so the
      // refusal's reason — how many rows matched — survives the trip.
      if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
        const text = await error.response.data.text();
        try {
          error.response.data = JSON.parse(text);
        } catch {
          error.response.data = { detail: text };
        }
      }
      throw error;
    }
  },
};
