import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";
import type {
  BomLine,
  BomMoveRequest,
  BomTreeResponse,
  CostBreakdownResponse,
} from "@/modules/maker/types/maker";

export type BoMSummaryResponse = components["schemas"]["BoMSummaryResponse"];

export type WhereUsedItem = components["schemas"]["WhereUsedItem"];

export type WhereUsedResponse =
  components["schemas"]["PaginatedResponse_WhereUsedItem_"];

export type BoMTemplateIdsResponse =
  components["schemas"]["BoMTemplateIdsResponse"];

export const bomApi = {
  /** Every product template in the organization that has a formula. */
  templateIdsWithBom: async (): Promise<BoMTemplateIdsResponse> => {
    const response = await api.get<BoMTemplateIdsResponse>(
      "/maker/bom/template-ids",
    );
    return response.data;
  },

  /** Batched BoM existence + line count for a list of templates. */
  summaryForTemplates: async (
    templateIds: string[],
  ): Promise<BoMSummaryResponse> => {
    const response = await api.get<BoMSummaryResponse>(`/maker/bom/summary`, {
      params: { template_ids: templateIds.join(",") },
    });
    return response.data;
  },

  /** Reverse BoM edge: recipes whose BoM consumes this template. */
  whereUsed: async (templateId: string): Promise<WhereUsedResponse> => {
    const response = await api.get<WhereUsedResponse>(`/maker/bom/where-used`, {
      params: { template_id: templateId },
    });
    return response.data;
  },

  /** Per-ingredient cost estimate (layer-average rates). Without params
   *  this answers one unit of the template's default formula; a specific
   *  formula and a batch quantity narrow it to the caller's own question. */
  getCostEstimate: async (
    templateId: string,
    params?: { recipeId?: string; qty?: string },
  ): Promise<CostBreakdownResponse> => {
    const response = await api.get<CostBreakdownResponse>(
      `/maker/bom/${templateId}/cost-estimate`,
      {
        params: {
          recipe_id: params?.recipeId,
          qty: params?.qty,
        },
      },
    );
    return response.data;
  },

  /** The tree under one recipe of the template — `recipeId`, else the
   *  default recipe. A product's variants each have their own. */
  getTree: async (
    templateId: string,
    recipeId?: string,
  ): Promise<BomTreeResponse> => {
    const response = await api.get<BomTreeResponse>(
      `/maker/bom/tree/${templateId}`,
      { params: { recipe_id: recipeId } },
    );
    return response.data;
  },

  moveLine: async (lineId: string, data: BomMoveRequest): Promise<BomLine> => {
    const response = await api.post<BomLine>(`/maker/bom/${lineId}/move`, data);
    return response.data;
  },
};
