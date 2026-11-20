import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { useHasPermission } from "@/module-sdk";

const WORKFLOW_MISSING = "PO_APPROVAL_WORKFLOW_MISSING";

/**
 * The toast for a failed confirm.
 *
 * The server's refusal for "this order needs an approval and no workflow
 * exists" tells the reader to ask their administrator. A person who may
 * configure workflows is that administrator, so they get the way to the
 * Create workflow form instead of a sentence sending them to themselves.
 */
export function usePOConfirmRefusalToast(): (err: unknown) => void {
  const { t } = useTranslation("purchase_orders");
  const navigate = useNavigate();
  const canConfigure = useHasPermission("approvals:configure");

  return useCallback(
    (err: unknown) => {
      if (canConfigure && extractApiErrorCode(err) === WORKFLOW_MISSING) {
        toast.error(t("approvalWorkflowMissingForAdmin"), {
          action: {
            label: t("settings.workflowMissing.action"),
            onClick: () =>
              navigate("/approvals/workflows?new=1&target=purchase_order"),
          },
        });
        return;
      }
      toast.error(extractApiError(err, t("unknownError")));
    },
    [canConfigure, navigate, t],
  );
}
