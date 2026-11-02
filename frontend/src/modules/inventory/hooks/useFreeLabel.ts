import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useConfirm } from "@/hooks/useConfirm";
import { useUnassignLabel } from "@/modules/shared/hooks/useLabels";

/**
 * Takes a label off the product it is attached to, after asking.
 *
 * A sticker put on the wrong product could only be put right by archiving
 * that product and freeing the label from the archive. Both places that show
 * the binding — the product page and the label pool — offer it through this,
 * so the question and the words are the same wherever the mistake is seen.
 * The screen renders `confirmDialogProps` in a `ConfirmDialog`.
 */
export function useFreeLabel() {
  const { t } = useTranslation(["labels", "inventory"]);
  const { confirm, confirmDialogProps } = useConfirm();
  const unassign = useUnassignLabel();

  const freeLabel = useCallback(
    async (code: string, productName?: string | null) => {
      const agreed = await confirm({
        title: t("labels:actions.freeLabelNamed", { code }),
        message: t("labels:actions.freeLabelConfirm", {
          code,
          name: productName || "—",
        }),
        confirmLabel: t("labels:actions.freeLabel"),
      });
      if (!agreed) return;
      unassign.mutate(code, {
        onSuccess: () =>
          toast.success(t("inventory:toasts.archivedLabelFreed")),
      });
    },
    [confirm, t, unassign],
  );

  return { freeLabel, isFreeing: unassign.isPending, confirmDialogProps };
}
