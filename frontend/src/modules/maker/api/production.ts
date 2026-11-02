import { api, getEveryPage } from "@/lib/api/client";
import type {
  MonthlyResultItem,
  ProductionOrder,
  ProductionOrderCancel,
  ProductionOrderComplete,
  ProductionOrderCreateInput,
  ProductionOrderListResponse,
  ProductionOrderUpdate,
  StockMove,
  ProductionPreviewResponse,
  ShortageShoppingListResponse,
} from "@/modules/maker/types/maker";

export const productionApi = {
  list: async (params?: {
    output_template_id?: string;
    status?: string;
    sort?: string;
    date_from?: string;
    date_to?: string;
    skip?: number;
    limit?: number;
  }): Promise<ProductionOrderListResponse> => {
    const response = await api.get<ProductionOrderListResponse>(
      "/maker/production/orders",
      { params },
    );
    return response.data;
  },

  get: async (orderId: string): Promise<ProductionOrder> => {
    const response = await api.get<ProductionOrder>(
      `/maker/production/orders/${orderId}`,
    );
    return response.data;
  },

  create: async (
    data: ProductionOrderCreateInput,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      "/maker/production/orders",
      data,
    );
    return response.data;
  },

  update: async (
    orderId: string,
    data: ProductionOrderUpdate,
  ): Promise<ProductionOrder> => {
    const response = await api.patch<ProductionOrder>(
      `/maker/production/orders/${orderId}`,
      data,
    );
    return response.data;
  },

  duplicate: async (orderId: string): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/duplicate`,
    );
    return response.data;
  },

  complete: async (
    orderId: string,
    data?: ProductionOrderComplete,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/complete`,
      data ?? {},
    );
    return response.data;
  },

  cancel: async (
    orderId: string,
    data?: ProductionOrderCancel,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/cancel`,
      data ?? {},
    );
    return response.data;
  },

  reverse: async (orderId: string): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/reverse`,
    );
    return response.data;
  },

  getStockMoves: async (orderId: string): Promise<StockMove[]> => {
    return getEveryPage<StockMove>(
      `/maker/production/orders/${orderId}/stock-moves`,
    );
  },

  preview: async (
    data: ProductionOrderCreateInput,
  ): Promise<ProductionPreviewResponse> => {
    const response = await api.post<ProductionPreviewResponse>(
      "/maker/production/orders/preview",
      data,
    );
    return response.data;
  },

  /** A run that already happened, created and completed in one step. */
  recordMade: async (
    data: ProductionOrderCreateInput,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      "/maker/production/orders/made",
      data,
    );
    return response.data;
  },

  /** Puts what a planned run lacks on the active shopping list. */
  shortagesToShoppingList: async (
    data: ProductionOrderCreateInput,
  ): Promise<ShortageShoppingListResponse> => {
    const response = await api.post<ShortageShoppingListResponse>(
      "/maker/production/orders/shortages/shopping-list",
      data,
    );
    return response.data;
  },

  monthlyResult: async (months?: number): Promise<MonthlyResultItem[]> => {
    const response = await api.get<MonthlyResultItem[]>(
      "/maker/production/monthly-result",
      { params: { months } },
    );
    return response.data;
  },
};
