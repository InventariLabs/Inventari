import { GripVertical, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { RoleMembersPicker } from "@/modules/approvals/components/RoleMembersPicker";
import { UserMultiSelect } from "@/modules/approvals/components/UserMultiSelect";
import {
  stageNamesSomebody,
  type StageDraft,
} from "@/modules/approvals/workflowStages";

interface ApprovalStageCardProps {
  stage: StageDraft;
  onChange: (stage: StageDraft) => void;
  onRemove: () => void;
}

/**
 * One stage of a workflow: what it is called and who decides it, side by
 * side, then the people when the stage names them.
 *
 * Who decides is a choice — the people named, or anyone holding the approve
 * permission — rather than the silent meaning of an empty list. The card used
 * to lead with a role picker that decided nothing; a role is now only a way
 * to add the people who hold it.
 *
 * The row that holds the fields holds nothing that can grow: the handle, the
 * label, the choice and the bin, all one field tall, so the captions stay on
 * one line and the handle and the bin stay on the inputs. On a phone the
 * choice and the people drop under the label and take the card's full width:
 * the label's column is too narrow there for an answer of three words.
 */
export function ApprovalStageCard({
  stage,
  onChange,
  onRemove,
}: ApprovalStageCardProps) {
  const { t } = useTranslation("approvals");
  const approversCaptionId = `stage-${stage.order}-approvers`;
  const approvers = stage.approver_user_ids;

  return (
    <div className="rounded-lg border border-border p-4">
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] gap-x-3 sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div className="contents" data-testid={`stage-header-${stage.order}`}>
          <div className="col-start-1 row-start-1 flex h-11 items-center gap-2 self-end text-on-muted md:h-10">
            <GripVertical size={18} />
            <span className="w-5 text-center text-sm font-medium tabular-nums">
              {stage.order}
            </span>
          </div>
          <div className="col-start-2 row-start-1">
            <Input
              label={t("workflows.stageLabel", "Stage Label")}
              placeholder={t("workflows.stageLabelPlaceholder")}
              value={stage.label}
              onChange={(e) => onChange({ ...stage, label: e.target.value })}
            />
          </div>
          <div className="col-[1/4] row-start-2 mt-3 sm:col-start-3 sm:row-start-1 sm:mt-0">
            <Select
              label={t("workflows.deciders")}
              value={stage.open ? "open" : "named"}
              onChange={(id) =>
                onChange(
                  id === "open"
                    ? { ...stage, open: true, approver_user_ids: [] }
                    : { ...stage, open: false },
                )
              }
              options={[
                { id: "named", name: t("workflows.decidersNamed") },
                { id: "open", name: t("workflows.decidersOpen") },
              ]}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("workflows.removeStage", "Remove stage")}
            onClick={onRemove}
            className="col-start-3 row-start-1 self-end sm:col-start-4"
          >
            <Trash2 size={16} className="text-on-muted" />
          </Button>
        </div>

        {!stage.open && (
          <div
            role="group"
            aria-labelledby={approversCaptionId}
            className="col-[1/4] row-start-3 mt-4 space-y-1.5 sm:col-[2/4] sm:row-start-2"
          >
            <p
              id={approversCaptionId}
              className="ml-1 text-xs font-medium uppercase tracking-wide text-on-secondary"
            >
              {t("workflows.approvers")}
            </p>
            <UserMultiSelect
              selectedUserIds={approvers}
              onChange={(ids) => onChange({ ...stage, approver_user_ids: ids })}
            />
            <RoleMembersPicker
              selectedUserIds={approvers}
              onAdd={(ids) =>
                onChange({
                  ...stage,
                  approver_user_ids: [...approvers, ...ids],
                })
              }
            />
            {!stageNamesSomebody(stage) && (
              <p className="ml-1 text-xs text-amber-600" role="note">
                {t("workflows.nameAnApprover")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
