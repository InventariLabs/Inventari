import { useMemo } from "react";
import { useModules } from "@/contexts/ModulesContext";

/**
 * What the approval state of a document means for the page: whether the
 * request is open, and whether execution is refused for want of one.
 */
interface ApprovalGateInput {
  docStatus?: string | null;
  approvalsEnabled: boolean;
  requirement?: { approval_required?: boolean; workflow_configured?: boolean };
  approval?: { status?: string | null } | null;
}

export interface ApprovalGate {
  hasPendingApproval: boolean;
  /** Approval is required and none is open or granted. */
  approvalRequiredNoRequest: boolean;
  /** ...and no workflow is active, so a request cannot be raised either. */
  approvalWorkflowMissing: boolean;
}

function approvalGate(input: ApprovalGateInput): ApprovalGate {
  const status = input.approval?.status;
  const hasPendingApproval = status === "PENDING" || status === "IN_PROGRESS";
  return {
    hasPendingApproval,
    approvalRequiredNoRequest:
      input.docStatus === "CONFIRMED" &&
      input.approvalsEnabled &&
      input.requirement?.approval_required === true &&
      status !== "APPROVED" &&
      !hasPendingApproval,
    approvalWorkflowMissing: input.requirement?.workflow_configured === false,
  };
}

/**
 * The state a document is worked in. One parked for a module switched off
 * since (`hold_stood_down`) is worked as the confirmed document it was: the
 * server starts a session on it and posts it, and its badge still says what
 * the row holds.
 */
export function workingStatus(doc: {
  status: string;
  hold_stood_down?: boolean;
}): string {
  return doc.hold_stood_down ? "CONFIRMED" : doc.status;
}

/** Execution the server would refuse is disabled instead of failing late. */
export function executionBlocked(gate: ApprovalGate): boolean {
  return gate.hasPendingApproval || gate.approvalRequiredNoRequest;
}

/** Why execution is blocked, as a translation key, or none. */
export function executionHintKey(gate: ApprovalGate): string | undefined {
  if (gate.hasPendingApproval) return "warehouse:actions.approvalPendingHint";
  if (!gate.approvalRequiredNoRequest) return undefined;
  return gate.approvalWorkflowMissing
    ? "warehouse:actions.approvalNoWorkflowHint"
    : "warehouse:actions.approvalRequiredHint";
}

/** The execution form opens only for a document the server would let through. */
export function executionPanelVisible(
  isConfirmed: boolean,
  executionOpen: boolean,
  gate: ApprovalGate,
  docType: string,
): boolean {
  return (
    isConfirmed &&
    executionOpen &&
    !gate.approvalRequiredNoRequest &&
    docType !== "CORRECTION"
  );
}

/** Stable across renders while the three reads are unchanged. */
export function useApprovalGate(
  docStatus: ApprovalGateInput["docStatus"],
  requirement: ApprovalGateInput["requirement"],
  approval: ApprovalGateInput["approval"],
): ApprovalGate {
  const { isModuleEnabled } = useModules();
  const approvalsEnabled = isModuleEnabled("approvals");
  return useMemo(
    () => approvalGate({ docStatus, approvalsEnabled, requirement, approval }),
    [docStatus, approvalsEnabled, requirement, approval],
  );
}
