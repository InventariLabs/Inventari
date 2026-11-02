import { useAppMutation } from "@/lib/api/mutationFactory";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { itemsApi } from "@/lib/api/items";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import { queryKeys } from "@/hooks/queries/keys";

export function useUpdateNutrition() {
  return useAppMutation(
    ({
      templateId,
      nutritionInfo,
    }: {
      templateId: string;
      nutritionInfo: ProductTemplateNutritionInfo;
      itemId?: string;
    }) => productTemplatesApi.updateNutrition(templateId, nutritionInfo),
    (qc, _result, { itemId }) => {
      if (itemId) {
        qc.invalidateQueries({
          queryKey: queryKeys.items.detail(itemId),
        });
      }
    },
  );
}

export function useSaveNutritionToItem() {
  return useAppMutation(
    ({
      itemId,
      metadata,
    }: {
      itemId: string;
      metadata: Record<string, unknown>;
    }) =>
      // The contract requires the flag; this write touches metadata only,
      // which is the flag's "no".
      itemsApi.update(itemId, {
        unit_confirmed_over_template: false,
        metadata,
      }),
    (qc, _result, { itemId }) => {
      qc.invalidateQueries({
        queryKey: queryKeys.items.detail(itemId),
      });
    },
  );
}
