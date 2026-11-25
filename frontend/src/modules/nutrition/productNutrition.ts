import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import type { Item } from "@/types";

export type NutrientKey = keyof ProductTemplateNutritionInfo;

/** The one list of figures both nutrition surfaces print, in their order. */
export const NUTRIENT_FIELDS: ReadonlyArray<{
  key: NutrientKey;
  unit: string;
}> = [
  { key: "calories_kcal", unit: "kcal" },
  { key: "protein_g", unit: "g" },
  { key: "fat_g", unit: "g" },
  { key: "saturated_fat_g", unit: "g" },
  { key: "carbs_g", unit: "g" },
  { key: "fiber_g", unit: "g" },
  { key: "sugar_g", unit: "g" },
  { key: "salt_g", unit: "g" },
];

/** What a record's own enrichment (Open Food Facts, a label scan) calls the same figure. */
const RECORD_NAMES: Record<NutrientKey, string> = {
  calories_kcal: "energy_kcal",
  protein_g: "proteins",
  fat_g: "fat",
  saturated_fat_g: "saturated_fat",
  carbs_g: "carbohydrates",
  fiber_g: "fiber",
  sugar_g: "sugars",
  salt_g: "salt",
};

const asNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const num = typeof value === "string" ? parseFloat(value) : Number(value);
  // Six significant digits: some figures were stored through a 32-bit float,
  // and 0.7 came back as 0.699999988079071 in the form's field.
  return Number.isFinite(num) ? Number(num.toPrecision(6)) : null;
};

const groupOf = (
  meta: Record<string, unknown> | null | undefined,
): Record<string, unknown> => {
  const group = meta?.nutrition;
  return group && typeof group === "object"
    ? (group as Record<string, unknown>)
    : {};
};

/**
 * The names a product's own figure may be stored under, its own first — the
 * table the recipe nutrition reads a product with (`_MACRO_ALIASES` in the
 * recipes module): a product created with Open Food Facts' names, or the older
 * `calories`, carries the figure all the same.
 */
const PRODUCT_NAMES: Record<NutrientKey, readonly string[]> =
  Object.fromEntries(
    NUTRIENT_FIELDS.map(({ key }) => [
      key,
      key === "calories_kcal"
        ? [key, "calories", RECORD_NAMES[key]]
        : [key, RECORD_NAMES[key]],
    ]),
  ) as Record<NutrientKey, readonly string[]>;

const firstOf = (
  group: Record<string, unknown>,
  names: readonly string[],
): number | null => {
  for (const name of names) {
    const value = asNumber(group[name]);
    if (value !== null) return value;
  }
  return null;
};

/**
 * The product's nutrition per 100 g, or null when nothing is known.
 *
 * A value typed in by hand is saved to the product, not to the record, and the
 * edit sheet reads that figure too.
 * The product's figure wins; the record's enrichment fills what it lacks.
 */
export function productNutrition(
  item: Pick<Item, "metadata" | "template">,
): ProductTemplateNutritionInfo | null {
  const product = groupOf(item.template?.meta_data);
  const record = groupOf(item.metadata);
  const values: ProductTemplateNutritionInfo = {};
  for (const { key } of NUTRIENT_FIELDS) {
    const value =
      firstOf(product, PRODUCT_NAMES[key]) ??
      asNumber(record[RECORD_NAMES[key]]);
    if (value !== null) values[key] = value;
  }
  return Object.keys(values).length > 0 ? values : null;
}

/**
 * Whether a record's figures were filled from Open Food Facts. The enrichment
 * names its source in more than one way — the importer's own label, the
 * database's name, and the capture flag — and every surface that says so must
 * agree on which of them count.
 */
export function isFromOpenFoodFacts(
  meta: Record<string, unknown> | null | undefined,
): boolean {
  const source = meta?.source;
  return (
    (typeof source === "string" &&
      (source === "local_off_db" || source.includes("Open Food Facts"))) ||
    meta?.nutrition_source === "off_db"
  );
}
