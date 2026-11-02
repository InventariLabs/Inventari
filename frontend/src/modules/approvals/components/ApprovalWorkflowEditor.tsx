import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { ApprovalStageCard } from "@/modules/approvals/components/ApprovalStageCard";
import { useOrgRoles } from "@/modules/approvals/hooks/useOrgRoles";
import type { StageDraft } from "@/modules/approvals/workflowStages";

interface ApprovalWorkflowEditorProps {
  stages: StageDraft[];
  onChange: (stages: StageDraft[]) => void;
}

export function ApprovalWorkflowEditor({
  stages,
  onChange,
}: ApprovalWorkflowEditorProps) {
  const { t } = useTranslation("approvals");

  const { data: roles = [], isError, isLoading } = useOrgRoles();

  // An open stage is decided by anyone holding the approve grant; a stage
  // nobody in the organization holds it at is a dead end, and the server
  // refuses it on save. The form can say so while the stage is being written
  // — the count of holders rides the roles payload, so with the payload
  // unavailable (403) there is nothing to warn with and nothing is said.
  const rolesKnown = !isError && !isLoading;
  const hasApproveHolder = roles.some(
    (role) =>
      role.member_count > 0 && role.permissions?.includes("approvals:approve"),
  );
  const hasOpenStage = stages.some((stage) => stage.open);

  // A new stage names people: who decides is picked, and leaving it to
  // anyone with the grant is a choice made on the card.
  const addStage = () => {
    const nextOrder =
      stages.length > 0 ? Math.max(...stages.map((s) => s.order)) + 1 : 1;
    onChange([
      ...stages,
      {
        order: nextOrder,
        // The suggestion is in the reader's language, like the first stage's.
        label: t("workflows.newStageLabel", { order: nextOrder }),
        approver_user_ids: [],
        open: false,
      },
    ]);
  };

  const updateStage = (index: number, stage: StageDraft) => {
    onChange(stages.map((s, i) => (i === index ? stage : s)));
  };

  const removeStage = (index: number) => {
    onChange(stages.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-on-muted">{t("workflows.roleApproverHint")}</p>
      {rolesKnown && !hasApproveHolder && hasOpenStage && (
        <p className="text-xs text-amber-600" role="note">
          {t("workflows.noApproverInOrganization")}
        </p>
      )}
      {stages.map((stage, index) => (
        <ApprovalStageCard
          key={index}
          stage={stage}
          onChange={(next) => updateStage(index, next)}
          onRemove={() => removeStage(index)}
        />
      ))}

      <Button
        type="button"
        variant="outline"
        leftIcon={<Plus size={16} />}
        onClick={addStage}
        className="w-full sm:w-auto"
      >
        {t("workflows.addStage", "Add Stage")}
      </Button>
    </div>
  );
}
