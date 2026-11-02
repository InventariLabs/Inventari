/**
 * One batch — GET /api/v1/stock-lots/{id}.
 *
 * Read-only: a batch changes state through quarantine and release, never
 * through this route. Its movements come from the ledger, narrowed by batch.
 */
import { api } from "./client";
import type { components } from "@/types/api-generated";

export type StockLotDetail = components["schemas"]["StockLotDetailDTO"];
export type StockLotsPage =
  components["schemas"]["PaginatedResponse_StockLotDetailDTO_"];
export type LotStatus = components["schemas"]["LotStatus"];

export interface StockLotFilters {
  product_template_id?: string;
  status?: LotStatus;
  limit?: number;
  offset?: number;
}

export const stockLotsApi = {
  get: async (lotId: string): Promise<StockLotDetail> => {
    const response = await api.get<StockLotDetail>(`/stock-lots/${lotId}`);
    return response.data;
  },

  list: async (filters: StockLotFilters = {}): Promise<StockLotsPage> => {
    const params: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params[key] = value;
    }
    const response = await api.get<StockLotsPage>("/stock-lots", { params });
    return response.data;
  },

  /**
   * Hold a batch back, or let it go again — and say why.
   *
   * The reason is required by the endpoint, releases included: a status with
   * nothing behind it answers a later question with "somebody clicked".
   */
  setStatus: async (
    lotId: string,
    status: LotStatus,
    reason: string,
  ): Promise<void> => {
    await api.patch(`/stock-lots/${lotId}`, { status, reason });
  },
};
