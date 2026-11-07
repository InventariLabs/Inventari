import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";

export type ProductSearchResult = components["schemas"]["ProductSearchResult"];

/**
 * A catalogue hit always names a template — only a stock search can answer with
 * an item that was never catalogued. Callers that need a template id (putaway
 * rules, pricelists) search the catalogue and get that guarantee in the type.
 */
export type CatalogueSearchResult = ProductSearchResult & {
  product_template_id: string;
};

interface QuickCreateStubPayload {
  name: string;
  barcode?: string;
}

export const documentsProductsApi = {
  productSearch: async (
    query: string,
    limit = 10,
  ): Promise<CatalogueSearchResult[]> => {
    const response = await api.get<CatalogueSearchResult[]>(
      "/warehouse/product-search",
      { params: { q: query, limit } },
    );
    return response.data;
  },

  /**
   * The stock on hand, narrowed to one location when given: a shelf is
   * exact, a zone also offers the shelves below it.
   *
   * Every result names an item, which is what a line taking goods off a shelf
   * has to reference — the stock executors move stock by record and refuse a
   * line without one. A scrap document names no location of its own, so its
   * search covers the organization: the record the person picks says which
   * shelf the goods leave from.
   */
  stockSearch: async (
    query: string,
    locationId?: string | null,
    limit = 10,
    merge = false,
  ): Promise<ProductSearchResult[]> => {
    const response = await api.get<ProductSearchResult[]>(
      "/warehouse/product-search",
      {
        params: {
          q: query,
          limit,
          stock: true,
          ...(locationId ? { location_id: locationId } : {}),
          // Only the executors that pull across records may take a merged
          // row — a transfer moves a single record.
          ...(merge ? { merge: true } : {}),
        },
      },
    );
    return response.data;
  },

  quickCreateStub: async (
    data: QuickCreateStubPayload,
  ): Promise<ProductSearchResult> => {
    const response = await api.post<ProductSearchResult>(
      "/warehouse/product-search/quick-create",
      data,
    );
    return response.data;
  },
};
