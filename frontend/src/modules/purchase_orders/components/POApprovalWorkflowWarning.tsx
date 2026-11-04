import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";
import { usePOApprovalWorkflowConfigured } from "../hooks/usePurchaseOrders";

interface POApprovalWorkflowWarningProps {
  /** The "require approval for all orders" switch is on. */
  requireAll: boolean;
  /** An approval threshold is set: orders above it need approval. */
  thresholdSet: boolean;
}

/**
 * Says out loud that the approval setting has nothing behind it.
 *
 * "Require approval" used to confirm the order anyway when no workflow
 * existed, so the manager who switched it on believed purchases were
 * controlled while every order sailed through. Confirmation is now
 * refused instead — which is only fair if the screen that switched the
 * requirement on also says what is missing and leads to where it is fixed.
 *
 * The one bit — "an active ``purchase_order`` workflow with a stage
 * exists" — comes from ``usePOApprovalWorkflowConfigured``, the same hook that
 * gates the request action on the order screen, so the warning and the
 * button can never disagree. The dedicated endpoint answers without the
 * ``approvals:read`` grant, so the manager who required approval sees the
 * warning even where the workflow list itself would be filtered away.
 */
export function POApprovalWorkflowWarning({
  requireAll,
  thresholdSet,
}: POApprovalWorkflowWarningProps) {
  const { t } = useTranslation("purchase_orders");
  const navigate = useNavigate();
  const { isModuleEnabled } = useModules();
  const approvalsEnabled = isModuleEnabled("approvals");
  const configured = usePOApprovalWorkflowConfigured();

  if ((!requireAll && !thresholdSet) || configured === true) return null;
  // While the module is on but the question is still unanswered — in flight
  // or failed — there is nothing honest to say; a warning that appears and
  // disappears reads as a glitch. With the module off the query never fires
  // by design and the answer stays ``undefined`` too; that case passes this
  // guard and speaks below, through the branch that leads to the apps
  // screen.
  if (approvalsEnabled && configured === undefined) return null;

  // With the switch off the requirement left is the threshold, so that is the
  // field the remedy names; "turn the requirement off" would point at a
  // checkbox that already is.
  const thresholdOnly = !requireAll;
  const body = approvalsEnabled
    ? {
        text: t(
          thresholdOnly
            ? "settings.workflowMissing.descriptionThreshold"
            : "settings.workflowMissing.description",
        ),
        action: t("settings.workflowMissing.action"),
        to: "/approvals/workflows?new=1&target=purchase_order",
      }
    : {
        text: t(
          thresholdOnly
            ? "settings.workflowMissing.moduleDescriptionThreshold"
            : "settings.workflowMissing.moduleDescription",
        ),
        action: t("settings.workflowMissing.moduleAction"),
        to: "/apps",
      };

  return (
    <div className="flex flex-col gap-3 rounded-xl bg-amber-100 px-4 py-3 text-on-warning sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-2">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-medium">
            {t("settings.workflowMissing.title")}
          </p>
          <p className="text-sm">{body.text}</p>
        </div>
      </div>
      <Button size="sm" className="shrink-0" onClick={() => navigate(body.to)}>
        {body.action}
      </Button>
    </div>
  );
}
