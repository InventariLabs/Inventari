import { api } from "@/lib/api/client";
import type {
  NeedsScope,
  NeedsView,
  OrderMissingResult,
  PlanIntermediatesResult,
} from "@/modules/maker/types/maker";

export const planningApi = {
  /** What the planned runs of a period (or one run) need, in one list. */
  needs: async (scope: NeedsScope): Promise<NeedsView> => {
    const response = await api.get<NeedsView>("/maker/production/needs", {
      params: scope,
    });
    return response.data;
  },

  /** A draft purchase order per supplier for what is missing. */
  orderMissing: async (scope: NeedsScope): Promise<OrderMissingResult> => {
    const response = await api.post<OrderMissingResult>(
      "/maker/production/needs/order",
      scope,
    );
    return response.data;
  },

  /** A planned run of each missing intermediate product. */
  planIntermediates: async (
    scope: NeedsScope,
  ): Promise<PlanIntermediatesResult> => {
    const response = await api.post<PlanIntermediatesResult>(
      "/maker/production/needs/plan-intermediates",
      scope,
    );
    return response.data;
  },
};
