import { useTranslation } from "react-i18next";
import { Check, XCircle, Circle, CircleDot } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDate } from "@/utils/formatters";
import { stageName } from "@/modules/approvals/workflowStages";
import type {
  ApprovalDecision,
  ApprovalRequest,
  StageDefinition,
} from "@/modules/approvals/api/approvals";

type StageStatus = "completed" | "rejected" | "current" | "upcoming";

interface ApprovalStageStepperProps {
  stages?: StageDefinition[] | null;
  currentStage: number;
  totalStages: number;
  status: ApprovalRequest["status"];
  decisions: ApprovalDecision[];
}

function classifyStage(
  stage: StageDefinition,
  currentStage: number,
  status: ApprovalRequest["status"],
  decisions: ApprovalDecision[],
): StageStatus {
  const decision = decisions.find((d) => d.stage_order === stage.order);
  if (decision?.status === "REJECTED") return "rejected";
  if (decision?.status === "APPROVED") return "completed";
  if (status === "APPROVED") return "completed";
  if (status === "REJECTED") return "upcoming";
  if (stage.order === currentStage) return "current";
  return "upcoming";
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "completed") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-100 text-accent-700">
        <Check size={14} strokeWidth={2.5} />
      </span>
    );
  }
  if (status === "rejected") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-red-100 text-red-600">
        <XCircle size={14} strokeWidth={2.5} />
      </span>
    );
  }
  if (status === "current") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-100 text-primary-600 ring-2 ring-primary-200">
        <CircleDot size={14} strokeWidth={2.5} />
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-inset text-on-muted">
      <Circle size={12} />
    </span>
  );
}

export function ApprovalStageStepper({
  stages,
  currentStage,
  totalStages,
  status,
  decisions,
}: ApprovalStageStepperProps) {
  const { t } = useTranslation("approvals");

  if (!stages || stages.length === 0) {
    // missing stage data must not be presented as a claim about the
    // process. With a multi-stage workflow the honest fallback is the
    // position ("Stage 2 of 2"), not "Single approval".
    if (totalStages > 1) {
      return (
        <p className="text-sm text-on-muted">
          {t("dashboard.stepper.stageOfTotal", {
            current: currentStage,
            total: totalStages,
          })}
        </p>
      );
    }
    return (
      <p className="text-sm text-on-muted">
        {t("dashboard.stepper.singleApproval")}
      </p>
    );
  }

  if (stages.length === 1) {
    // A single-stage workflow used to collapse to the bare label,
    // which dropped the decision — including the rejection reason the
    // approver is required to type. Most workflows have exactly one stage,
    // so this was the common case, not the edge case.
    const stage = stages[0];
    const decision = decisions.find((d) => d.stage_order === stage.order);
    const stageStatus = classifyStage(stage, currentStage, status, decisions);
    return (
      <div>
        <p className="text-sm font-medium text-on">{stageName(stage)}</p>
        {stageStatus === "completed" && decision && (
          <CompletedMeta decision={decision} />
        )}
        {stageStatus === "rejected" && decision && (
          <RejectedMeta decision={decision} />
        )}
      </div>
    );
  }

  const lastIndex = stages.length - 1;

  return (
    <ol role="list" className="space-y-0">
      {stages.map((stage, idx) => {
        const stageStatus = classifyStage(
          stage,
          currentStage,
          status,
          decisions,
        );
        const decision = decisions.find((d) => d.stage_order === stage.order);
        const isLast = idx === lastIndex;
        const approverCount = stage.approver_user_ids.length;

        return (
          <li key={stage.order} className="flex gap-3">
            <div className="flex flex-col items-center">
              <StageIcon status={stageStatus} />
              {!isLast && (
                <span
                  aria-hidden
                  className={cn(
                    "mt-1 w-px flex-1 min-h-3",
                    stageStatus === "completed" ? "bg-accent-200" : "bg-border",
                  )}
                />
              )}
            </div>
            <div className={cn("flex-1", !isLast && "pb-3")}>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-sm font-medium",
                    stageStatus === "upcoming" ? "text-on-muted" : "text-on",
                  )}
                >
                  {stageName(stage)}
                </span>
                {stageStatus === "current" && (
                  <span className="rounded-full bg-primary-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary-700">
                    {t("dashboard.stepper.current")}
                  </span>
                )}
              </div>

              {stageStatus === "completed" && decision && (
                <CompletedMeta decision={decision} />
              )}

              {stageStatus === "rejected" && decision && (
                <RejectedMeta decision={decision} />
              )}

              {stageStatus === "current" && approverCount > 0 && (
                <p className="mt-0.5 text-xs text-on-muted">
                  {t("dashboard.stepper.approversAssigned", {
                    count: approverCount,
                  })}
                </p>
              )}

              {stageStatus === "current" && approverCount === 0 && (
                <p className="mt-0.5 text-xs text-on-muted">
                  {t("request.anyApprover")}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// The server stamps this prefix on a stage it passed on the requester's
// behalf (sole approver); such a stage must not read like a decision.
export const AUTO_PASSED_NOTE_PREFIX = "Auto-approved:";

function CompletedMeta({ decision }: { decision: ApprovalDecision }) {
  const { t } = useTranslation("approvals");
  const autoPassed = decision.notes?.startsWith(AUTO_PASSED_NOTE_PREFIX);
  return (
    <div className="mt-0.5 text-xs text-on-muted">
      {decision.approver_name && <span>{decision.approver_name}</span>}
      {decision.decided_at && (
        <span>
          {" · "}
          {formatDate(decision.decided_at)}
        </span>
      )}
      {autoPassed ? (
        <div className="italic text-on-secondary">
          {t("request.autoPassed")}
        </div>
      ) : (
        decision.notes && (
          <div className="italic text-on-secondary">"{decision.notes}"</div>
        )
      )}
    </div>
  );
}

function RejectedMeta({ decision }: { decision: ApprovalDecision }) {
  return (
    <div className="mt-0.5 text-xs text-red-600">
      {decision.approver_name && <span>{decision.approver_name}</span>}
      {decision.decided_at && (
        <span>
          {" · "}
          {formatDate(decision.decided_at)}
        </span>
      )}
      {decision.notes && (
        <div className="italic text-red-700">"{decision.notes}"</div>
      )}
    </div>
  );
}
