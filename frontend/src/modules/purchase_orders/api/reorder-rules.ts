import { api, getEveryPage } from "@/lib/api/client";
import type { WithServerDefaults } from "@/types/request";
import type { components } from "@/types/api-generated";

export type ReorderRule = components["schemas"]["ReorderRuleSchema"];

export type ReorderRuleCreate = components["schemas"]["ReorderRuleCreate"];

/** What a caller sends: an unsaid safety stock is the server's default. */
export type ReorderRuleCreateInput = WithServerDefaults<
  ReorderRuleCreate,
  "safety_stock"
>;

export type ReorderRuleUpdate = components["schemas"]["ReorderRuleUpdate"];

export interface ReorderRuleListParams {
  product_template_id?: string;
  location_id?: string;
}

export const reorderRulesApi = {
  list: async (params?: ReorderRuleListParams): Promise<ReorderRule[]> => {
    return getEveryPage<ReorderRule>("/purchase-orders/reorder-rules", params);
  },

  getById: async (id: string): Promise<ReorderRule> => {
    const response = await api.get<ReorderRule>(
      `/purchase-orders/reorder-rules/${id}`,
    );
    return response.data;
  },

  create: async (data: ReorderRuleCreateInput): Promise<ReorderRule> => {
    const response = await api.post<ReorderRule>(
      "/purchase-orders/reorder-rules",
      data,
    );
    return response.data;
  },

  update: async (id: string, data: ReorderRuleUpdate): Promise<ReorderRule> => {
    const response = await api.patch<ReorderRule>(
      `/purchase-orders/reorder-rules/${id}`,
      data,
    );
    return response.data;
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/purchase-orders/reorder-rules/${id}`);
  },
};

// ── Replenishment alerts (documents stock router) ────────────────────

export type ReplenishmentAlert = components["schemas"]["ReplenishmentAlertDTO"];

export type ReplenishmentDraftPosResult =
  components["schemas"]["ReplenishmentDraftPosResult"];

export const replenishmentApi = {
  listAlerts: async (): Promise<ReplenishmentAlert[]> =>
    getEveryPage<ReplenishmentAlert>("/purchase-orders/replenishment/alerts"),

  createDraftPos: async (
    reorderRuleIds: string[],
  ): Promise<ReplenishmentDraftPosResult> => {
    const response = await api.post<ReplenishmentDraftPosResult>(
      "/purchase-orders/replenishment/draft-pos",
      { reorder_rule_ids: reorderRuleIds },
    );
    return response.data;
  },
};
