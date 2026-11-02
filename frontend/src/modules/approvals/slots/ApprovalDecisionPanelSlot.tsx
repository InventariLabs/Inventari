import { useTranslation } from "react-i18next";

import { ApprovalDecisionPanel } from "@/modules/approvals/components/ApprovalDecisionPanel";
import { ApprovalStageStepper } from "@/modules/approvals/components/ApprovalStageStepper";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

/**
 * How far a request has got, and the decision on it, for a target module's
 * queue card. On a narrow screen the decision comes first and the progress
 * after it; from `xl` the progress leads. The target module supplies the
 * adapters, so approving or rejecting moves the entity too — the generic
 * `/approvals/requests/{id}/reject` would leave a document stuck in
 * PENDING_APPROVAL.
 */
export function ApprovalDecisionPanelSlot({
  data: { approval, onApprove, onReject },
}: {
  data: SlotDataMap["approval_decision_panel"];
}) {
  const { t } = useTranslation("approvals");

  return (
    <div className="flex flex-col gap-4">
      <div className="order-2 xl:order-1">
        <p className="mb-2 text-[10px] font-medium uppercase tracking-widest text-on-muted">
          {t("dashboard.section.approvalProgress")}
        </p>
        <ApprovalStageStepper
          stages={approval.workflow_stages}
          currentStage={approval.current_stage}
          totalStages={approval.total_stages}
          status={approval.status}
          decisions={approval.decisions}
        />
      </div>
      <ApprovalDecisionPanel
        className="order-1 xl:order-2"
        approval={approval}
        onApprove={onApprove}
        onReject={onReject}
      />
    </div>
  );
}
