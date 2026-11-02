import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useApprovalWorkflows } from "@/modules/approvals/hooks/useApprovalWorkflows";
import { useCanReadWorkflows } from "@/modules/approvals/hooks/useApprovalPermissions";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";

/** Whether a document workflow exists, or whether that cannot be told yet. */
type WorkflowState = "active" | "none" | "unknown";

type ConsequenceId =
  "guarded" | "noWorkflow" | "needsWorkflow" | "workflowOnly" | "nothing";

/**
 * The sentence that says what the configured combination does to a document.
 *
 * The rule the server applies, spelled out for the reader who is composing
 * it: the profile says what needs approval, the workflow says who approves,
 * and only a silent profile lets the workflow stand in for it. Each state
 * gets the sentence that matches it — none is left to inference, and the
 * two that used to be conflated (a profile outside a workflow, and a
 * workflow overriding a profile) now read differently.
 *
 * ``null`` only when the workflow cannot be told and nothing asks for it —
 * there is no honest sentence then.
 */
function consequenceId(
  workflow: WorkflowState,
  profileNamesWhat: boolean,
): ConsequenceId | null {
  if (profileNamesWhat) {
    if (workflow === "active") return "guarded";
    if (workflow === "none") return "noWorkflow";
    return "needsWorkflow";
  }
  if (workflow === "active") return "workflowOnly";
  if (workflow === "none") return "nothing";
  return null;
}

/**
 * Each sentence as its own ``t()`` call, not a key looked up in a map: the
 * i18n gate reads literals, and a family reached through a variable loses
 * both halves of its protection — a key deleted from the catalog would
 * render as its own name, and the orphan check would never say so.
 */
function ConsequenceSentence({ id }: { id: ConsequenceId }) {
  const { t } = useTranslation("approvals");
  switch (id) {
    case "guarded":
      return <>{t("documentSetup.consequenceGuarded")}</>;
    case "noWorkflow":
      return <>{t("documentSetup.consequenceNoWorkflow")}</>;
    case "needsWorkflow":
      return <>{t("documentSetup.consequenceNeedsWorkflow")}</>;
    case "workflowOnly":
      return <>{t("documentSetup.consequenceWorkflowOnly")}</>;
    case "nothing":
      return <>{t("documentSetup.consequenceNothing")}</>;
  }
}

/**
 * Says what the approval settings do — with a workflow and without one.
 *
 * "Require approval" used to confirm the document anyway when no workflow
 * existed, so the manager who switched it on believed documents were
 * controlled while every one sailed through. Confirmation is now refused
 * instead — which is only fair if the screen that switched the requirement
 * on also says what is missing and leads to where it is fixed.
 *
 * The other half is the rule itself: once a workflow exists, the profile
 * settings decide which documents wait, and only a profile that names
 * nothing lets the workflow demand approval for every document. The two
 * used to be one sentence ("the workflow demands every document"), which
 * the server then applied whatever the threshold said — so the consequence
 * is stated per combination, from the same state the warning reads.
 */
export function DocumentApprovalSetupNoticeSlot({
  data: { approvalRequested },
}: {
  data: SlotDataMap["document_approval_setup_notice"];
}) {
  const { t } = useTranslation("approvals");
  const navigate = useNavigate();
  const { data: workflows, isLoading, isError } = useApprovalWorkflows();
  const canReadWorkflows = useCanReadWorkflows();

  const hasWorkflow = (workflows ?? []).some(
    (workflow) => workflow.target_type === "document" && workflow.is_active,
  );
  // The server filters the workflow list to readers, so for an account
  // without the grant it is always empty: not "no workflow", but "not yours
  // to see". That, a failed fetch and the in-flight list all answer
  // "unknown" — an empty list is only evidence once it was readable.
  const workflowState: WorkflowState =
    isLoading || isError || !canReadWorkflows
      ? "unknown"
      : hasWorkflow
        ? "active"
        : "none";
  const consequence = consequenceId(workflowState, approvalRequested);

  // While the workflows are still loading there is nothing honest to say —
  // a warning that appears and disappears reads as a glitch.
  const showWarning =
    approvalRequested && !hasWorkflow && !isLoading && canReadWorkflows;
  if (!showWarning && consequence === null) return null;

  return (
    <div className="space-y-4">
      {showWarning && (
        <div className="flex flex-col gap-3 rounded-xl bg-amber-100 px-4 py-3 text-on-warning sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium">
                {t("documentSetup.workflowMissing.title")}
              </p>
              <p className="text-sm">
                {t("documentSetup.workflowMissing.description")}
              </p>
            </div>
          </div>
          <Button
            size="sm"
            className="shrink-0"
            onClick={() =>
              navigate("/approvals/workflows?new=1&target=document")
            }
          >
            {t("documentSetup.workflowMissing.action")}
          </Button>
        </div>
      )}
      {consequence && (
        <p
          data-testid="approval-consequence"
          className="rounded-xl border border-border/60 bg-surface-inset px-4 py-3 text-sm text-on-secondary"
        >
          <ConsequenceSentence id={consequence} />
        </p>
      )}
    </div>
  );
}
