import { useAppMutation } from "@/lib/api/mutationFactory";
import { itemsApi } from "@/lib/api/items";
import { labelsApi } from "@/lib/api/labels";
import type { LabelScanView } from "@/types";
import type { LeftAmount } from "../components/PartlyUsedSheet";
import { api } from "@/module-sdk";
import { invalidation } from "@/lib/api/invalidation";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

export function useScanConsume() {
  const { t } = useTranslation("labels");

  return useAppMutation(
    ({ itemId, quantity }: { itemId: string; quantity: number }) =>
      itemsApi.consume(itemId, quantity),
    (qc) => {
      invalidation.items(qc);
      toast.success(t("items:quickActions.consumedSuccess"));
    },
  );
}

/**
 * "Use partially" from a scan: open the package or say how much is left, then
 * read the scan again. The split changes which records the product has, so the
 * sheet is refreshed from the server rather than patched in place.
 */
export function useScanUsePartially(
  scanned: LabelScanView | null,
  onRescanned: (data: LabelScanView) => void,
) {
  const mutation = useAppMutation(
    ({
      itemId,
      left,
      leftUomId,
      useBy,
    }: {
      itemId: string;
      left?: number;
      leftUomId?: string;
      useBy?: string;
    }) =>
      itemsApi.openPartly(itemId, {
        left,
        left_uom_id: leftUomId,
        use_by: useBy,
      }),
    (qc) => {
      invalidation.items(qc);
    },
  );
  return async (itemId: string, amount: LeftAmount) => {
    await mutation.mutateAsync({ itemId, ...amount });
    if (scanned) onRescanned(await labelsApi.scan(scanned.label_code));
  };
}

export function useScanUpdateQuantity() {
  const { t } = useTranslation("labels");

  return useAppMutation(
    ({ itemId, quantity }: { itemId: string; quantity: number }) =>
      itemsApi.updateQuantity(itemId, quantity),
    (qc) => {
      invalidation.items(qc);
      toast.success(t("quickAdd.success"));
    },
  );
}

/**
 * Put the scanned product on the newest active shopping list, making one when
 * there is none. The lists are the shopping-lists module's, written over its
 * HTTP routes with this module's own client: that module is optional here,
 * and an import of its files cannot be.
 */
export function useScanAddToShoppingList() {
  const { t: tScan } = useTranslation("scan");

  return useAppMutation(
    async ({ templateName }: { templateName: string }) => {
      const { data: active } = await api.get<{ items: { id: string }[] }>(
        "/shopping-lists",
        { params: { active_only: true, limit: 1 } },
      );
      let listId = active.items[0]?.id;
      if (!listId) {
        const { data: created } = await api.post<{ id: string }>(
          "/shopping-lists",
          { name: tScan("defaultShoppingListName") },
        );
        listId = created.id;
      }
      await api.post(`/shopping-lists/${listId}/items`, {
        name: templateName,
        quantity: 1,
      });
      return templateName;
    },
    (qc, templateName) => {
      invalidation.items(qc);
      toast.success(tScan("addedToShoppingList", { name: templateName }));
    },
  );
}
