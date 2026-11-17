import { api, getEveryPage } from "@/lib/api/client";
import type {
  MonthlyResultItem,
  ProductionOrder,
  ProductionOrderCancel,
  ProductionOrderComplete,
  ProductionMadeCreateInput,
  ProductionOrderCreateInput,
  ProductionOrderFinish,
  ProductionOrderStart,
  ProductionPortionCreate,
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
    planned_from?: string;
    planned_to?: string;
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

  /** Takes the ingredients now; the run is finished later. */
  start: async (
    orderId: string,
    data?: ProductionOrderStart,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/start`,
      data ?? {},
    );
    return response.data;
  },

  /** Puts part of an in-progress run's output on the shelf. */
  addPortion: async (
    orderId: string,
    data: ProductionPortionCreate,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/portions`,
      data,
    );
    return response.data;
  },

  /** Closes an in-progress run: the rest of its output and its final cost. */
  finish: async (
    orderId: string,
    data?: ProductionOrderFinish,
  ): Promise<ProductionOrder> => {
    const response = await api.post<ProductionOrder>(
      `/maker/production/orders/${orderId}/finish`,
      data ?? {},
    );
    return response.data;
  },

  /** Marks one process step done on a day, or clears it (`done_on` null). */
  tickStep: async (
    orderId: string,
    index: number,
    doneOn: string | null,
  ): Promise<ProductionOrder> => {
    const response = await api.put<ProductionOrder>(
      `/maker/production/orders/${orderId}/steps/${index}`,
      { done_on: doneOn },
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
    data: ProductionMadeCreateInput,
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
