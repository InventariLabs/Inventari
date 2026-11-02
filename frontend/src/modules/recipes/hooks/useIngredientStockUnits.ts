import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { productTemplatesApi } from "@/lib/api/productTemplates";

/** What a row needs to know about its ingredient's stock unit. */
export interface IngredientStockUnit {
  uomId: string;
  /** The units of the weight and the volume the card states per stock unit.
   *  With them the maker reads a line in g/ml as the stocked pieces — and a
   *  picker that offers only the piece is hiding a door the guard would
   *  open. Empty when the card states neither. */
  measureUomIds: string[];
}

/**
 * The unit each linked ingredient is kept in, by template id.
 *
 * The maker refuses a BoM line whose unit cannot be read as the ingredient's
 * stock unit, and the stock unit lives on the product template — not on the
 * ingredient row, which carries only the template id. The recipe editor asks
 * the catalogue for it so the unit picker can offer what the guard accepts
 * rather than letting the refusal be the first word the reader hears of it.
 * Unlinked ingredients have no template and therefore no stock unit; they are
 * simply absent from the map, and their rows keep the free picker.
 *
 * A failed read is not "no stock units": the rows would offer the free
 * picker and meet the refusal at save, so the failure comes back beside the
 * map for the caller to say.
 */
export function useIngredientStockUnits(templateIds: Array<string | null>): {
  stockUnits: Record<string, IngredientStockUnit>;
  isError: boolean;
  error: unknown;
  refetch: () => void;
} {
  const ids = useMemo(
    () => [...new Set(templateIds.filter((id): id is string => Boolean(id)))],
    [templateIds],
  );

  const { data, isError, error, refetch } = useQuery({
    queryKey: queryKeys.recipes.ingredientStockUnits(ids),
    enabled: ids.length > 0,
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<Record<string, IngredientStockUnit>> => {
      const pairs = await Promise.all(
        ids.map(async (id) => {
          const template = await productTemplatesApi.get(id);
          if (!template.uom_id) return null;
          return [
            id,
            {
              uomId: template.uom_id,
              measureUomIds: [
                template.weight_value != null ? template.weight_uom_id : null,
                template.volume_value != null ? template.volume_uom_id : null,
              ].filter((id): id is string => Boolean(id)),
            },
          ] as const;
        }),
      );
      return Object.fromEntries(
        pairs.filter((pair): pair is readonly [string, IngredientStockUnit] =>
          Boolean(pair),
        ),
      );
    },
  });

  return {
    stockUnits: data ?? {},
    isError,
    error,
    refetch: () => void refetch(),
  };
}
