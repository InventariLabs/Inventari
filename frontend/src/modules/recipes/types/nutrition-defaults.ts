// Ingredient nutrition defaults and unit conversions.
import type { components } from "@/types/api-generated";

/**
 * One default row. Taken from the schema rather than retyped: the
 * hand-written copy typed every nutrition figure a number, where the wire
 * carries Decimals as strings (TECHNICAL_DECISIONS §18) — readers convert
 * with the formatters instead of trusting arithmetic that concatenates.
 */
export type IngredientDefault =
  components["schemas"]["IngredientDefaultSchema"];

export type IngredientDefaultListResponse =
  components["schemas"]["PaginatedResponse_IngredientDefaultSchema_"];

export type IngredientDefaultLookupResponse =
  components["schemas"]["IngredientDefaultLookupResponse"];

export type IngredientDefaultCreate =
  components["schemas"]["IngredientDefaultCreate"];

export type ImportDefaultsResult =
  components["schemas"]["ImportDefaultsResult"];

/** One conversion. A mirror of `UnitConversionSchema` under the shorter
 *  name; `metric_quantity` crosses the wire as a Decimal string. */
export type UnitConversion = components["schemas"]["UnitConversionSchema"];

export type UnitConversionCreate =
  components["schemas"]["UnitConversionCreate"];

export type UnitConversionUpdate =
  components["schemas"]["UnitConversionUpdate"];
