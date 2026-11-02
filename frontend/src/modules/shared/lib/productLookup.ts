import type { components } from "@/types/api-generated";
import { api } from "@/lib/api/client";

/**
 * Finding a product by the barcode on its packaging, or by the name being
 * typed into a form.
 *
 * This is not a documents question — the endpoint is the item catalogue's —
 * but it lived in the documents API client because the receipt form needed it
 * first. Order lines and the document line list both scan the same codes, so
 * it belongs where either of them can reach it without importing the other
 * module's internals.
 *
 * The name door answers with the *same* matching the item create path uses,
 * so a form showing "this product is counted in kilograms" and the record
 * that lands after the save cannot disagree about the unit.
 */
export type ProductTemplateLookupResult =
  components["schemas"]["ProductTemplateLookupResult"];

/** What the lookup may be asked with. At least one of the two is required. */
export interface ProductLookupQuery {
  barcode?: string;
  name?: string;
  brand?: string;
}

/**
 * A product template by barcode and/or name — `null` when nothing matches.
 * The endpoint answers that `null` itself rather than a 404, which the
 * browser logged as an error for every new product a form typed.
 */
export async function lookupProduct(
  query: ProductLookupQuery,
): Promise<ProductTemplateLookupResult | null> {
  const response = await api.get<ProductTemplateLookupResult | null>(
    "/items/product-templates/lookup",
    { params: query },
  );
  return response.data ?? null;
}

export async function lookupProductByBarcode(
  barcode: string,
): Promise<ProductTemplateLookupResult | null> {
  return lookupProduct({ barcode });
}
