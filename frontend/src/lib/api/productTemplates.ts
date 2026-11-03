import { api } from "./client";
import type { components } from "@/types/api-generated";

export interface ProductTemplateNutritionInfo {
  calories_kcal?: number | null;
  protein_g?: number | null;
  fat_g?: number | null;
  carbs_g?: number | null;
  fiber_g?: number | null;
  sugar_g?: number | null;
  salt_g?: number | null;
}

/** A product template. Taken from the schema rather than retyped: the
 *  hand-written copy dropped the weight-uom/volume fields and `min_quantity`
 *  the endpoint already sends. */
export type ProductTemplate = components["schemas"]["ProductTemplate"];

/** Longest search text the endpoint takes; a product name may be longer. */
const SEARCH_MAX_LENGTH = 100;

export const productTemplatesApi = {
  get: async (templateId: string): Promise<ProductTemplate> => {
    const { data } = await api.get(`/items/product-templates/${templateId}`);
    return data;
  },

  /** A name longer than the endpoint's limit is searched by its opening —
   *  sending all of it would be refused outright. */
  search: async (query: string, limit = 10): Promise<ProductTemplate[]> => {
    const { data } = await api.get(`/items/product-templates`, {
      params: { search: query.slice(0, SEARCH_MAX_LENGTH), limit },
    });
    return data;
  },

  /** Create a product from a name and a unit — the whole record a quick
   *  create needs; everything else the product form offers can follow.
   *  A scanned code goes with it, or the next scan would not find it. */
  create: async (
    name: string,
    uomId: string,
    codes?: { brand?: string; barcode?: string },
  ): Promise<ProductTemplate> => {
    const { data } = await api.post(`/items/product-templates`, {
      name,
      uom_id: uomId,
      brand: codes?.brand || undefined,
      barcode: codes?.barcode || undefined,
    });
    return data;
  },

  /** A fresh internal EAN-13 for a product without a manufacturer's code.
   *  Nothing is assigned: the form puts it in the field and the save
   *  writes it. */
  generateBarcode: async (): Promise<string> => {
    const { data } = await api.post<
      components["schemas"]["GeneratedProductCode"]
    >(`/items/product-templates/generate-barcode`);
    return data.barcode;
  },

  /** Count of templates the org can pick from. */
  count: async (): Promise<number> => {
    const { data } = await api.get(`/items/product-templates/count`);
    return data.count;
  },

  /** How much of this product the organization holds, summed the way the
   *  low-stock threshold is measured — internal locations only. The screen
   *  that sets a threshold needs this, not the quantity of whichever
   *  record the reader happened to open. */
  getStock: async (
    templateId: string,
  ): Promise<{
    product_template_id: string;
    total_quantity: string;
    uom_symbol: string | null;
  }> => {
    const { data } = await api.get(
      `/items/product-templates/${templateId}/stock`,
    );
    return data;
  },

  updateNutrition: async (
    templateId: string,
    nutritionInfo: ProductTemplateNutritionInfo | null,
  ): Promise<void> => {
    await api.patch(`/items/product-templates/${templateId}/nutrition`, {
      nutrition_info: nutritionInfo,
    });
  },
};
