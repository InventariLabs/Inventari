import { api } from "@/lib/api/client";
import type { CostBreakdownResponse } from "@/modules/maker/types/maker";

export const breakdownApi = {
  forTemplate: async (
    templateId: string,
    qty: string,
    recipeId?: string | null,
  ): Promise<CostBreakdownResponse> => {
    const response = await api.get<CostBreakdownResponse>(
      `/maker/breakdown/${templateId}`,
      { params: recipeId ? { qty, recipe_id: recipeId } : { qty } },
    );
    return response.data;
  },
};
