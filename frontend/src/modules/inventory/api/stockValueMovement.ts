/**
 * What the stock was worth over a period — GET /api/v1/stock-value-movement.
 *
 * The same refusals as the stock on a date: a period that opens before the
 * ledger's first movement comes back as a 400 naming the boundary, and that
 * sentence is the answer.
 */
import axios from "axios";
import { api, type components } from "@/module-sdk";

export type StockValueMovement = components["schemas"]["StockValueMovementDTO"];

export interface StockValueMovementQuery {
  /**
   * The first day of the period, `YYYY-MM-DD`. Left out, the server opens it
   * on the first day it can report for the month of `date_to`.
   */
  date_from?: string;
  /** The last day of the period, included. */
  date_to: string;
}

export const stockValueMovementApi = {
  get: async (query: StockValueMovementQuery): Promise<StockValueMovement> => {
    const response = await api.get<StockValueMovement>(
      "/stock-value-movement",
      { params: query },
    );
    return response.data;
  },

  /** Asking for a blob means the refusal arrives as one too. */
  exportXlsx: async (query: StockValueMovementQuery): Promise<Blob> => {
    try {
      const response = await api.get("/stock-value-movement/export/xlsx", {
        params: query,
        responseType: "blob",
      });
      return response.data as Blob;
    } catch (error) {
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
