import { api, getEveryPage } from "@/lib/api/client";
import type {
  BatchRecord,
  IngredientBatchPlanResponse,
  OutputBatch,
  ProductionAttachment,
  ShelfLife,
} from "@/modules/maker/types/maker";

/** What the ingredient batch plan is asked for: the run as its form names it. */
export interface IngredientBatchQuery {
  output_template_id: string;
  planned_qty: string;
  output_location_id: string;
  recipe_id?: string | null;
}

const ORDERS = "/maker/production/orders";

/**
 * A run's batches: the output's shelf life, hold and record, the batches its
 * ingredients are taken from, and the files filed under it.
 */
export const batchesApi = {
  ingredientBatches: async (
    query: IngredientBatchQuery,
  ): Promise<IngredientBatchPlanResponse> => {
    const { recipe_id, ...rest } = query;
    const response = await api.get<IngredientBatchPlanResponse>(
      "/maker/production/ingredient-batches",
      { params: recipe_id ? { ...rest, recipe_id } : rest },
    );
    return response.data;
  },

  shelfLife: async (templateId: string): Promise<ShelfLife> => {
    const response = await api.get<ShelfLife>(
      `/maker/production/shelf-lives/${templateId}`,
    );
    return response.data;
  },

  setShelfLife: async (
    templateId: string,
    days: number | null,
  ): Promise<ShelfLife> => {
    const response = await api.put<ShelfLife>(
      `/maker/production/shelf-lives/${templateId}`,
      { shelf_life_days: days },
    );
    return response.data;
  },

  hold: async (orderId: string, reason: string): Promise<OutputBatch> => {
    const response = await api.post<OutputBatch>(`${ORDERS}/${orderId}/hold`, {
      reason,
    });
    return response.data;
  },

  release: async (orderId: string): Promise<OutputBatch> => {
    const response = await api.post<OutputBatch>(
      `${ORDERS}/${orderId}/release`,
    );
    return response.data;
  },

  record: async (orderId: string): Promise<BatchRecord> => {
    const response = await api.get<BatchRecord>(`${ORDERS}/${orderId}/record`);
    return response.data;
  },

  attachments: async (orderId: string): Promise<ProductionAttachment[]> =>
    getEveryPage<ProductionAttachment>(`${ORDERS}/${orderId}/attachments`),

  uploadAttachment: async (
    orderId: string,
    file: File,
  ): Promise<ProductionAttachment> => {
    const form = new FormData();
    form.append("file", file);
    const response = await api.post<ProductionAttachment>(
      `${ORDERS}/${orderId}/attachments`,
      form,
    );
    return response.data;
  },

  deleteAttachment: async (
    orderId: string,
    attachmentId: string,
  ): Promise<void> => {
    await api.delete(`${ORDERS}/${orderId}/attachments/${attachmentId}`);
  },
};
