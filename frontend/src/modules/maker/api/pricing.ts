import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";

type PricingResponse = components["schemas"]["PricingResponse"];

type MarginResponse = components["schemas"]["MarginResponse"];

export type PricingRequest = components["schemas"]["PricingRequest"];

export const pricingApi = {
  compute: async (req: PricingRequest): Promise<PricingResponse> => {
    const response = await api.post<PricingResponse>(
      "/maker/pricing/compute",
      req,
    );
    return response.data;
  },

  getMargin: async (templateId: string): Promise<MarginResponse> => {
    const response = await api.get<MarginResponse>(
      `/maker/pricing/margin/${templateId}`,
    );
    return response.data;
  },

  setMargin: async (
    templateId: string,
    targetMarginPct: string,
  ): Promise<MarginResponse> => {
    const response = await api.put<MarginResponse>(
      `/maker/pricing/margin/${templateId}`,
      { target_margin_pct: targetMarginPct },
    );
    return response.data;
  },
};
