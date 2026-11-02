import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import type { ApprovalWorkflow } from "@/modules/approvals/api/approvals";
import { describeRequesters } from "@/modules/approvals/workflowRequesters";
import {
  useApprovalWorkflows,
  useUpdateWorkflow,
} from "@/modules/approvals/hooks/useApprovalWorkflows";
import {
  describeWorkflowScope,
  scopeSettingsPath,
} from "@/modules/approvals/workflowScope";

interface WorkflowActivationDialogProps {
  /** The workflow about to be switched on, or null while the dialog is shut. */
  workflow: ApprovalWorkflow | null;
  onClose: () => void;
}

/**
 * Switching a workflow on is its own act, and the reader is told first what
 * it will hold.
 *
 * A workflow used to come into force the moment it was saved: a document
 * workflow under a silent document profile then held every confirmed
 * document, and nothing on the screen said so. The scope comes from the
 * module that owns the gate, and the link goes to the settings that change
 * it, so a reader who did not mean "everything" can narrow it before saying
 * yes.
 *
 * The consent is to what the dialog shows, so the dialog shows the live
 * answer: it re-reads the list when it opens, and sends the scope it showed
 * with the switch-on. If the settings moved in between — another tab,
 * another administrator — the server refuses with a 409, which the mutation
 * factory answers by re-reading every query, so the reader sees the new rule
 * with the server's sentence before saying yes again; the button waits while
 * the list is fetched. A refused switch keeps the dialog open.
 */
export function WorkflowActivationDialog({
  workflow,
  onClose,
}: WorkflowActivationDialogProps) {
  const { t } = useTranslation("approvals");
  const updateWorkflow = useUpdateWorkflow();
  const { data: workflows, refetch, isFetching } = useApprovalWorkflows();

  const workflowId = workflow?.id ?? null;
  useEffect(() => {
    if (workflowId !== null) void refetch();
  }, [workflowId, refetch]);

  // The freshest row the list holds, not the one the card was drawn from.
  const current = workflows?.find((wf) => wf.id === workflowId) ?? workflow;
  const scope = current?.scope ?? null;
  const phrase =
    current && scope
      ? describeWorkflowScope(t, current.target_type, scope)
      : null;
  const message =
    phrase === null
      ? t("workflows.activateMessageUnknown")
      : scope?.holds === "nothing"
        ? t("workflows.activateMessageNothing", { scope: phrase })
        : t("workflows.activateMessage", { scope: phrase });
  const settingsPath = current ? scopeSettingsPath(current.target_type) : null;

  const switchOn = async () => {
    if (!current) return;
    await updateWorkflow.mutateAsync({
      id: current.id,
      data: {
        is_active: true,
        ...(scope ? { expected_scope: scope } : {}),
      },
    });
    toast.success(t("workflows.activated"));
    onClose();
  };

  return (
    <ConfirmDialog
      open={workflow !== null}
      title={t("workflows.activateTitle", { name: current?.name ?? "" })}
      message={message}
      confirmLabel={t("workflows.activateConfirm")}
      confirmDisabled={isFetching}
      onConfirm={switchOn}
      onCancel={onClose}
    >
      {current && (
        <p className="text-sm text-on-secondary">
          {describeRequesters(t, current)}
        </p>
      )}
      {settingsPath && (
        <Link
          to={settingsPath}
          className="text-sm font-medium text-primary-600 hover:text-primary-700 hover:underline"
        >
          {t("workflows.activateSettingsLink")}
        </Link>
      )}
    </ConfirmDialog>
  );
}
