import { useMemo } from "react";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import type {
  CategoryDTO,
  FieldDefinition,
  StorageLocationSummary,
} from "@/types";
import { computeFieldDefinitions } from "./computeFieldDefinitions";

interface UseFieldDefinitionsProps {
  // The categories endpoints answer CategoryDTO; its field_definitions are
  // typed as open dicts on the wire, so the renderer narrows them once,
  // inside computeFieldDefinitions.
  selectedCategory: CategoryDTO | undefined;
  selectedStorage: StorageLocationSummary | undefined;
  uomCategoryName: string | null;
  scannedAsFood?: boolean;
}

/**
 * What the item form draws, given what is selected and whether the
 * organization shows stock value.
 *
 * computeFieldDefinitions owns the rules; the "Show inventory value" switch
 * is one of their inputs — where it is off, the purchase-price field goes,
 * as the price goes from the record overview. Read here so the form hook
 * just consumes the list.
 */
export function useFieldDefinitions({
  selectedCategory,
  selectedStorage,
  uomCategoryName,
  scannedAsFood,
}: UseFieldDefinitionsProps): FieldDefinition[] {
  const showInventoryValue = useShowInventoryValue();

  return useMemo(
    () =>
      computeFieldDefinitions({
        selectedCategory,
        selectedStorage,
        uomCategoryName,
        showInventoryValue,
        scannedAsFood,
      }),
    [
      selectedCategory,
      selectedStorage,
      uomCategoryName,
      showInventoryValue,
      scannedAsFood,
    ],
  );
}
