import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useWorkflowWaiting } from "@/modules/approvals/hooks/useApprovalWorkflows";
import { targetTypeLabel } from "@/modules/approvals/targetTypes";
import type { ApprovalWorkflow } from "@/modules/approvals/api/approvals";

export type SwitchOffMode = "deactivate" | "delete";

interface WorkflowSwitchOffDialogProps {
  /** The workflow about to be switched off; `null` keeps the dialog closed. */
  workflow: ApprovalWorkflow | null;
  mode: SwitchOffMode;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

/**
 * Asks before a workflow is deactivated or deleted, and says in numbers what
 * that does: how many documents, orders and checkouts wait on it, that they go
 * on without approval, and which setting still demands one — releasing items
 * into a second dead end is the thing this dialog exists to prevent.
 */
export function WorkflowSwitchOffDialog({
  workflow,
  mode,
  onConfirm,
  onCancel,
}: WorkflowSwitchOffDialogProps) {
  const { t } = useTranslation(["approvals", "common"]);
  const {
    data: waiting,
    isLoading,
    isError,
  } = useWorkflowWaiting(workflow?.id ?? null);

  const parts: string[] = [
    mode === "delete"
      ? t("deleteWorkflowConfirm")
      : t("workflows.deactivateConfirm"),
  ];
  if (waiting && waiting.total > 0) {
    const list = waiting.waiting
      .map((w) =>
        t("workflows.waitingItem", {
          target: targetTypeLabel(t, w.target_type),
          number: w.count,
        }),
      )
      .join(", ");
    parts.push(t("workflows.waitingRelease", { list }));
  }
  // The consequence differs by target: a released document stops at completion
  // while the setting stands; a released order is simply confirmed, and the
  // setting only refuses new orders.
  const demanding = waiting?.settings_requiring_approval ?? [];
  // Which consequence applies follows the workflow's target, not the name of
  // the setting: an order's threshold is still an order setting.
  const forOrders = workflow?.target_type === "purchase_order";
  const orderSettings = forOrders ? demanding : [];
  const documentSettings = forOrders ? [] : demanding;
  const settingNames: Record<string, string> = {
    approval_required: t("workflows.demandSetting_approval_required"),
    approval_required_for_types: t(
      "workflows.demandSetting_approval_required_for_types",
    ),
    approval_threshold: t("workflows.demandSetting_approval_threshold"),
  };
  const named = (names: string[]) =>
    names.map((name) => settingNames[name] ?? name).join(", ");
  if (documentSettings.length > 0) {
    parts.push(
      t("workflows.demandWarningDocuments", {
        settings: named(documentSettings),
      }),
    );
  }
  if (orderSettings.length > 0) {
    parts.push(
      t("workflows.demandWarningOrders", { settings: named(orderSettings) }),
    );
  }

  return (
    <ConfirmDialog
      open={workflow !== null}
      title={
        mode === "delete" ? t("deleteWorkflow") : t("workflows.deactivateTitle")
      }
      message={
        isLoading
          ? t("common:messages.loading")
          : isError
            ? t("workflows.waitingUnavailable")
            : parts.join(" ")
      }
      variant="danger"
      confirmLabel={
        mode === "delete"
          ? t("common:actions.delete")
          : t("workflows.deactivate")
      }
      confirmDisabled={isLoading || isError}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
