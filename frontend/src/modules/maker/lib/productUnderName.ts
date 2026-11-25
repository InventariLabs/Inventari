/**
 * The product a recipe makes, for the line under the recipe's name — or
 * nothing when it would repeat the name: a recipe named after its product
 * ("Soy candle" making "Soy candle") has nothing to add under its title.
 */
export function productUnderName(recipe: {
  name: string;
  output_template_name?: string | null;
}): string | undefined {
  const product = recipe.output_template_name?.trim();
  if (!product) return undefined;
  return product.toLocaleLowerCase() === recipe.name.trim().toLocaleLowerCase()
    ? undefined
    : product;
}
