import type { components } from "@/types/api-generated";
import { api, getEveryPage } from "@/lib/api/client";

/**
 * The organization's tax rates, and the products and categories naming one.
 *
 * Backend: app/modules/warehouse/tax_rate_router.py. A new document or order
 * line that states no rate takes its product's, then its category's, then
 * the profile's or the country's default.
 */
export type TaxRate = components["schemas"]["TaxRateOut"];
export type TaxRateCreate = components["schemas"]["TaxRateCreate"];
export type TaxRateUpdate = components["schemas"]["TaxRateUpdate"];
export type CountryRates = components["schemas"]["CountryRatesOut"];
export type CategoryTaxRate = components["schemas"]["CategoryTaxRateOut"];
export type ProductTaxRate = components["schemas"]["ProductTaxRateOut"];

export const taxRatesApi = {
  list: async (): Promise<TaxRate[]> =>
    getEveryPage<TaxRate>("/warehouse/tax-rates"),

  create: async (data: TaxRateCreate): Promise<TaxRate> => {
    const response = await api.post<TaxRate>("/warehouse/tax-rates", data);
    return response.data;
  },

  update: async (id: string, data: TaxRateUpdate): Promise<TaxRate> => {
    const response = await api.put<TaxRate>(`/warehouse/tax-rates/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/warehouse/tax-rates/${id}`);
  },

  /** The standard and reduced rates the organization's country knows. */
  countryRates: async (): Promise<CountryRates> => {
    const response = await api.get<CountryRates>(
      "/warehouse/tax-rates/country",
    );
    return response.data;
  },

  listCategoryRates: async (): Promise<CategoryTaxRate[]> =>
    getEveryPage<CategoryTaxRate>("/warehouse/tax-rates/categories"),

  nameCategoryRate: async (
    categoryId: string,
    taxRateId: string | null,
  ): Promise<void> => {
    await api.put(`/warehouse/tax-rates/categories/${categoryId}`, {
      tax_rate_id: taxRateId,
    });
  },

  productRate: async (templateId: string): Promise<ProductTaxRate> => {
    const response = await api.get<ProductTaxRate>(
      `/warehouse/tax-rates/products/${templateId}`,
    );
    return response.data;
  },

  nameProductRate: async (
    templateId: string,
    taxRateId: string | null,
  ): Promise<ProductTaxRate> => {
    const response = await api.put<ProductTaxRate>(
      `/warehouse/tax-rates/products/${templateId}`,
      { tax_rate_id: taxRateId },
    );
    return response.data;
  },
};
