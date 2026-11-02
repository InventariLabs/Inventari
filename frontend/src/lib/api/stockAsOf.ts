/**
 * What the warehouse held on a day — GET /api/v1/stock-as-of.
 *
 * Refuses rather than guesses: a date before the ledger's first movement
 * comes back as a 400 naming the boundary, and that sentence is the answer,
 * not an error to swallow.
 */
import axios from "axios";
import { api } from "./client";
import type { components } from "@/types/api-generated";

export type StockAsOfReport = components["schemas"]["StockAsOfReportDTO"];

export interface StockAsOfQuery {
  as_of: string;
  location_id?: string;
  /** The screen's page; the files leave both out and carry every row. */
  limit?: number;
  offset?: number;
}

function toParams(query: StockAsOfQuery): Record<string, unknown> {
  const params: Record<string, unknown> = { as_of: query.as_of };
  if (query.location_id) params.location_id = query.location_id;
  if (query.limit !== undefined) params.limit = query.limit;
  if (query.offset !== undefined) params.offset = query.offset;
  return params;
}

/** Asking for a blob means the refusal arrives as one too. */
async function unwrapBlobError(error: unknown): Promise<never> {
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

export const stockAsOfApi = {
  get: async (query: StockAsOfQuery): Promise<StockAsOfReport> => {
    const response = await api.get<StockAsOfReport>("/stock-as-of", {
      params: toParams(query),
    });
    return response.data;
  },

  exportXlsx: async (query: StockAsOfQuery): Promise<Blob> => {
    try {
      const response = await api.get("/stock-as-of/export/xlsx", {
        params: toParams(query),
        responseType: "blob",
      });
      return response.data as Blob;
    } catch (error) {
      return unwrapBlobError(error);
    }
  },

  exportPdf: async (query: StockAsOfQuery): Promise<Blob> => {
    try {
      const response = await api.get("/stock-as-of/export/pdf", {
        params: toParams(query),
        responseType: "blob",
      });
      return response.data as Blob;
    } catch (error) {
      return unwrapBlobError(error);
    }
  },
};
