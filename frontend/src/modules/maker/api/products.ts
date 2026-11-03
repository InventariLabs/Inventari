import { api } from "@/lib/api/client";
import { clampProductSearch } from "@/module-sdk";

/**
 * A product the maker module can point at — as an output or an ingredient.
 *
 * Same shape the documents picker returns, deliberately: the module used to
 * import that type and call `/warehouse/product-search`, which 403s for an
 * organization that has the warehouse module switched off. Maker declares
 * `requires: ["items", "locations"]` and nothing more, so it now reads and
 * writes product templates through core.
 */
export interface ProductOption {
  product_template_id: string;
  name: string;
  sku: string | null;
  barcode: string | null;
  brand: string | null;
  uom_id: string | null;
  uom_symbol: string | null;
  image_url: string | null;
  is_stub: boolean;
}

interface ProductTemplateResponse {
  id: string;
  name: string;
  sku: string | null;
  barcode: string | null;
  brand: string | null;
  uom_id: string | null;
  image_url: string | null;
  meta_data?: Record<string, unknown> | null;
}

function toOption(template: ProductTemplateResponse): ProductOption {
  return {
    product_template_id: template.id,
    name: template.name,
    sku: template.sku,
    barcode: template.barcode,
    brand: template.brand,
    uom_id: template.uom_id,
    // Core returns the UoM id, not its symbol; callers that need a symbol
    // resolve it from the UoM list they already load.
    uom_symbol: null,
    image_url: template.image_url,
    is_stub: template.meta_data?.is_stub === true,
  };
}

export const makerProductsApi = {
  /** Fuzzy name search over the org's product templates (min. 2 chars). */
  search: async (query: string, limit = 10): Promise<ProductOption[]> => {
    const response = await api.get<ProductTemplateResponse[]>(
      "/items/product-templates",
      { params: { search: clampProductSearch(query), limit } },
    );
    return response.data.map(toOption);
  },

  /**
   * Create a product from the formula sheet. Name and unit together are the
   * whole record here: without a unit every number the module later shows —
   * batch yield, planned quantity, cost per unit, availability — would be a
   * bare digit with no measure behind it.
   */
  create: async (name: string, uomId: string): Promise<ProductOption> => {
    const response = await api.post<ProductTemplateResponse>(
      "/items/product-templates",
      { name, uom_id: uomId },
    );
    return toOption(response.data);
  },
};
