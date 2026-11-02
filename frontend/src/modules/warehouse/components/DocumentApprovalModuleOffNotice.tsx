import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useHasPermission } from "@/hooks/useHasPermission";

/**
 * What the approval settings come to while the Approvals module is off: no
 * document waits, whatever the threshold says. Stands in for the notice the
 * module itself contributes to the settings (`document_approval_setup_notice`)
 * — a workspace without the module still has to be told that a requirement
 * set here has nothing behind it, and where to switch the module on.
 */
export function DocumentApprovalModuleOffNotice({
  approvalRequested,
}: {
  /** Whether the settings on screen ask for approval at all. */
  approvalRequested: boolean;
}) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  // The same gate the module's own notice applies: only an account that can
  // see the approval setup is told it is missing.
  const canRead = useHasPermission("approvals:read");
  const canConfigure = useHasPermission("approvals:configure");
  const canReadSetup = canRead || canConfigure;

  return (
    <div className="space-y-4">
      {approvalRequested && canReadSetup && (
        <div className="flex flex-col gap-3 rounded-xl bg-amber-100 px-4 py-3 text-on-warning sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">
                {t("profile.workflowMissing.title")}
              </p>
              <p className="text-sm">
                {t("profile.workflowMissing.moduleDescription")}
              </p>
            </div>
          </div>
          <Button
            size="sm"
            className="shrink-0"
            onClick={() => navigate("/apps")}
          >
            {t("profile.workflowMissing.moduleAction")}
          </Button>
        </div>
      )}
      <p
        data-testid="approval-consequence"
        className="rounded-xl border border-border/60 bg-surface-inset px-4 py-3 text-sm text-on-secondary"
      >
        {t("profile.approvalConsequenceModuleOff")}
      </p>
    </div>
  );
}
