import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";

export type PartnerPricelist = components["schemas"]["PartnerPricelistSchema"];

export type PartnerPricelistCreate =
  components["schemas"]["PartnerPricelistCreate"];

export type PartnerPricelistUpdate =
  components["schemas"]["PartnerPricelistUpdate"];

export interface PricelistListParams {
  active_on?: string;
  product_template_id?: string;
}

export const pricelistApi = {
  listForPartner: async (
    partnerId: string,
    params?: PricelistListParams,
  ): Promise<PartnerPricelist[]> => {
    return getEveryPage<PartnerPricelist>(
      `/purchase-orders/pricelist/by-partner/${partnerId}`,
      params,
    );
  },

  listForTemplate: async (templateId: string): Promise<PartnerPricelist[]> => {
    return getEveryPage<PartnerPricelist>(
      `/purchase-orders/pricelist/by-template/${templateId}`,
    );
  },

  bestForTemplate: async (
    templateId: string,
    params?: { on_date?: string; quantity?: number },
  ): Promise<PartnerPricelist | null> => {
    const response = await api.get<PartnerPricelist | null>(
      `/purchase-orders/pricelist/best-for-template/${templateId}`,
      { params },
    );
    return response.data;
  },

  getById: async (id: string): Promise<PartnerPricelist> => {
    const response = await api.get<PartnerPricelist>(
      `/purchase-orders/pricelist/${id}`,
    );
    return response.data;
  },

  create: async (data: PartnerPricelistCreate): Promise<PartnerPricelist> => {
    const response = await api.post<PartnerPricelist>(
      "/purchase-orders/pricelist",
      data,
    );
    return response.data;
  },

  update: async (
    id: string,
    data: PartnerPricelistUpdate,
  ): Promise<PartnerPricelist> => {
    const response = await api.patch<PartnerPricelist>(
      `/purchase-orders/pricelist/${id}`,
      data,
    );
    return response.data;
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/purchase-orders/pricelist/${id}`);
  },
};
