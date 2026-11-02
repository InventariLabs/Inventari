import {
  productTemplatesApi,
  type ProductTemplate,
} from "@/lib/api/productTemplates";
import type { ProductComboboxOption } from "@/components/ui/ProductCombobox";

/**
 * Catalogue search in the shape `ProductCombobox` asks for.
 *
 * Recipes attach an ingredient to a product with it — the import review row
 * and the availability row each had written their own search box around this
 * same call: a raw input, a hand-rolled result list, no debounce, no keyboard,
 * and no answer at all while a search was in flight. A purchase-order receipt
 * names with it the product an order line typed by hand arrives as.
 */
export async function searchProductTemplates(
  query: string,
): Promise<ProductComboboxOption[]> {
  const templates = await productTemplatesApi.search(query);
  return templates.map(toOption);
}

/**
 * A product made on the spot from a typed name, in the combobox's shape so
 * it can be handed straight into the pick that links it.
 */
export async function createProductTemplate(
  name: string,
  uomId: string,
): Promise<ProductComboboxOption> {
  return toOption(await productTemplatesApi.create(name, uomId));
}

function toOption(template: ProductTemplate): ProductComboboxOption {
  return {
    product_template_id: template.id,
    name: template.name,
    sku: template.sku,
    barcode: template.barcode,
    image_url: template.image_url,
  };
}
