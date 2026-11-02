import { useTranslation } from "react-i18next";

import type { ApprovalWorkflow } from "@/modules/approvals/api/approvals";
import { describeWorkflowScope } from "@/modules/approvals/workflowScope";

/**
 * What a workflow holds, under its stages on the card.
 *
 * A workflow that is on states what waits on it; one that is off says it
 * holds nothing yet, and what it would hold once switched on — the same
 * phrase the switch-on dialog uses, so the card never reads one way and the
 * dialog another. A target type whose module gave no scope shows nothing.
 */
export function WorkflowScopeLine({
  workflow,
}: {
  workflow: ApprovalWorkflow;
}) {
  const { t } = useTranslation("approvals");
  if (!workflow.scope) return null;
  const scope = describeWorkflowScope(t, workflow.target_type, workflow.scope);
  return (
    <p className="mt-2 text-xs text-on-secondary">
      {workflow.is_active
        ? t("workflows.scopeOn", { scope })
        : t("workflows.scopeOff", { scope })}
    </p>
  );
}
