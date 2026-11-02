import { useTranslation } from "react-i18next";

import type { ApprovalWorkflow } from "@/modules/approvals/api/approvals";
import { describeRequesters } from "@/modules/approvals/workflowRequesters";

/**
 * Whose submissions a workflow holds, under what it holds on the card.
 *
 * Shown at all times, on or off: it is part of what the workflow is, and the
 * switch-on dialog repeats the same sentence.
 */
export function WorkflowRequestersLine({
  workflow,
}: {
  workflow: ApprovalWorkflow;
}) {
  const { t } = useTranslation("approvals");
  return (
    <p
      data-testid={`workflow-requesters-${workflow.id}`}
      className="mt-1 text-xs text-on-secondary"
    >
      {describeRequesters(t, workflow)}
    </p>
  );
}
