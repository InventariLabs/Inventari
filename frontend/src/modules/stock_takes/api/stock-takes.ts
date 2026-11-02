import { api, getEveryPage } from "@/lib/api/client";
import type {
  StockTake,
  StockTakeCreateInput,
  StockTakeUpdate,
  StockTakeItem,
  StockTakeReport,
  StockTakeListResponse,
  StockTakeStatus,
  ShelfClosed,
  LocationCountState,
} from "@/modules/stock_takes/types/stock-takes";

export const stockTakesApi = {
  getAll: async (params?: {
    location_id?: string;
    status_filter?: StockTakeStatus;
    offset?: number;
    limit?: number;
  }): Promise<StockTakeListResponse> => {
    const response = await api.get<StockTakeListResponse>("/stock-takes", {
      params,
    });
    return response.data;
  },

  getById: async (id: string): Promise<StockTake> => {
    const response = await api.get<StockTake>(`/stock-takes/${id}`);
    return response.data;
  },

  create: async (data: StockTakeCreateInput): Promise<StockTake> => {
    const response = await api.post<StockTake>("/stock-takes", data);
    return response.data;
  },

  update: async (id: string, data: StockTakeUpdate): Promise<StockTake> => {
    const response = await api.put<StockTake>(`/stock-takes/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/stock-takes/${id}`);
  },

  getItems: async (
    stockTakeId: string,
    params?: {
      include_counted?: boolean;
      include_discrepancies?: boolean;
      search?: string;
    },
  ): Promise<StockTakeItem[]> => {
    return getEveryPage<StockTakeItem>(
      `/stock-takes/${stockTakeId}/items`,
      params,
    );
  },

  complete: async (
    stockTakeId: string,
    applyAdjustments: boolean = true,
    notes?: string,
    forceOverCap: boolean = false,
    forceOverTolerance: boolean = false,
  ): Promise<StockTakeReport> => {
    const response = await api.post<StockTakeReport>(
      `/stock-takes/${stockTakeId}/complete`,
      {
        apply_adjustments: applyAdjustments,
        notes,
        force_over_cap: forceOverCap,
        force_over_tolerance: forceOverTolerance,
      },
    );
    return response.data;
  },

  getLocationStates: async (): Promise<LocationCountState[]> => {
    return getEveryPage<LocationCountState>("/stock-takes/locations");
  },

  getReport: async (stockTakeId: string): Promise<StockTakeReport> => {
    const response = await api.get<StockTakeReport>(
      `/stock-takes/${stockTakeId}/report`,
    );
    return response.data;
  },

  cancel: async (stockTakeId: string): Promise<StockTake> => {
    const response = await api.patch<StockTake>(
      `/stock-takes/${stockTakeId}/status`,
      { status: "cancelled" },
    );
    return response.data;
  },

  addItem: async (
    stockTakeId: string,
    data: {
      item_id: string;
      counted_quantity: number;
      notes?: string | null;
      /** The shelf the goods were found on, when it is not the record's own. */
      location_id?: string;
    },
  ): Promise<StockTakeItem> => {
    const response = await api.post<StockTakeItem>(
      `/stock-takes/${stockTakeId}/items`,
      data,
    );
    return response.data;
  },

  /** Close a location of the count: what nobody counted there becomes 0. */
  closeLocation: async (
    stockTakeId: string,
    locationId: string,
  ): Promise<ShelfClosed> => {
    const response = await api.post<ShelfClosed>(
      `/stock-takes/${stockTakeId}/locations/${locationId}/close`,
    );
    return response.data;
  },

  // the path segment is StockTakeItem.id, NOT the product (Item) id —
  // the backend resolves it via get_stock_take_item_or_404.
  requestRecount: async (
    stockTakeId: string,
    stockTakeItemId: string,
  ): Promise<StockTakeItem> => {
    const response = await api.post<StockTakeItem>(
      `/stock-takes/${stockTakeId}/items/${stockTakeItemId}/recount`,
    );
    return response.data;
  },

  countItem: async (
    stockTakeId: string,
    stockTakeItemId: string,
    data: {
      counted_quantity: number;
      notes?: string | null;
      discrepancy_reason_code?: string | null;
      discrepancy_reason?: string | null;
    },
  ): Promise<StockTakeItem> => {
    const response = await api.patch<StockTakeItem>(
      `/stock-takes/${stockTakeId}/items/${stockTakeItemId}/count`,
      data,
    );
    return response.data;
  },
};
