import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useResetTemplateToBuiltIn } from "@/modules/shared/hooks/useDocumentTemplates";
import type {
  DocumentTemplate,
  TemplateUrlSegment,
} from "@/modules/shared/lib/templates";

/** What a screen's own confirmation dialog answers to (see `useConfirm`). */
type Confirm = (options: {
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: "danger";
}) => Promise<boolean>;

/**
 * "Reset to built-in" for a template card: the one template action that
 * throws the organization's own work away, so it says so before it does and
 * names the result afterwards. Every screen that lists copies of a built-in
 * hands its own `confirm` and gets the same question and the same words.
 */
export function useConfirmedTemplateReset(
  module: TemplateUrlSegment,
  confirm: Confirm,
) {
  const { t } = useTranslation("common");
  const resetMutation = useResetTemplateToBuiltIn(module);

  const handleReset = async (tpl: DocumentTemplate) => {
    const ok = await confirm({
      title: t("templates.resetTitle", { name: tpl.name }),
      message: t("templates.resetMessage"),
      variant: "danger",
      confirmLabel: t("templates.resetConfirm"),
    });
    if (ok) {
      resetMutation.mutate(tpl.id, {
        onSuccess: (reset) =>
          toast.success(t("templates.resetDone", { name: reset.name })),
      });
    }
  };

  return { handleReset, isResetPending: resetMutation.isPending };
}
