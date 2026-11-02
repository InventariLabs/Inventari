import type { StageDefinition } from "@/modules/approvals/api/approvals";

/**
 * A stage as the workflow form edits it: who decides is a choice.
 *
 * On the wire an empty approver list is an open stage — anyone holding the
 * approve permission decides it. Left implicit in the form, that meant a stage
 * whose people had not been picked yet was silently open to everybody. The
 * form holds the choice as `open` and the save sends the wire shape.
 */
export interface StageDraft {
  order: number;
  label: string;
  approver_user_ids: string[];
  open: boolean;
}

export function toStageDraft(stage: StageDefinition): StageDraft {
  const approvers = stage.approver_user_ids ?? [];
  return {
    order: stage.order,
    label: stage.label,
    approver_user_ids: approvers,
    open: approvers.length === 0,
  };
}

export function toStageDefinition(draft: StageDraft): StageDefinition {
  return {
    order: draft.order,
    label: draft.label,
    approver_user_ids: draft.open ? [] : draft.approver_user_ids,
  };
}

/** Whether somebody decides the stage: anyone with the grant, or a named person. */
export function stageNamesSomebody(draft: StageDraft): boolean {
  return draft.open || draft.approver_user_ids.length > 0;
}

/**
 * What to call a stage on screen. The editor lets a label be cleared, and a
 * stage without one must still read as a stage — by its order, the same
 * fallback the server uses when it names a stage in a refusal.
 */
export function stageName(stage: Pick<StageDefinition, "order" | "label">) {
  return stage.label?.trim() || `#${stage.order}`;
}
