import { useTranslation } from "react-i18next";
import {
  StatusTimeline,
  type StatusTimelineStep,
} from "@/components/ui/StatusTimeline";
import {
  approvalDate,
  type DocumentApprovalTrace,
} from "@/modules/warehouse/components/documentConfirmation";

export type { DocumentApprovalTrace };

interface DocumentStatusTimelineProps {
  status: string;
  createdAt: string | null;
  confirmedAt: string | null;
  completedAt: string | null;
  cancelledAt?: string | null;
  /** The document's approval request, whatever became of it, or null. */
  approval?: DocumentApprovalTrace | null;
  formatDate: (dateStr: string | null) => string;
  isCorrection?: boolean;
}

/**
 * Where a document stands: Draft → Confirmed → Completed, with the
 * approval rung shown for every document that went through one.
 *
 * The rungs come from what the document went through, not from where it
 * is now. Built from the current status, the ladder showed a dated
 * "Confirmed" rung while the document waited for its approval and
 * dropped the approval the moment the decision came in — so the one card
 * that could show a document had been approved stopped showing it
 * exactly when that became a fact about the past. A ladder is a history;
 * a history that forgets is a badge with extra dots.
 */
function buildTimelineSteps(
  status: string,
  createdAt: string | null,
  confirmedAt: string | null,
  completedAt: string | null,
  cancelledAt: string | null,
  approval: DocumentApprovalTrace | null | undefined,
  isCorrection?: boolean,
): Omit<StatusTimelineStep, "label">[] {
  // A request the document raised — including one already decided.
  // `CANCELLED` is a withdrawn request: the document never passed
  // through that rung.
  const wentThroughApproval =
    status === "PENDING_APPROVAL" ||
    (approval != null && approval.status !== "CANCELLED");

  if (status === "CANCELLED") {
    return [
      { key: "DRAFT", date: createdAt, state: "complete" },
      ...(wentThroughApproval && approval
        ? [
            {
              key: "PENDING_APPROVAL",
              date: approvalDate(approval),
              state: "complete" as const,
            },
          ]
        : []),
      { key: "CANCELLED", date: cancelledAt, state: "current" },
    ];
  }

  // Corrections skip the CONFIRMED step — they go DRAFT → COMPLETED ("Applied")
  if (isCorrection) {
    return [
      {
        key: "DRAFT",
        date: createdAt,
        state: status === "DRAFT" ? "current" : "complete",
      },
      {
        key: "COMPLETED",
        date: completedAt,
        state: status === "COMPLETED" ? "current" : "upcoming",
      },
    ];
  }

  const orderedStatuses: string[] = wentThroughApproval
    ? ["DRAFT", "PENDING_APPROVAL", "CONFIRMED", "COMPLETED"]
    : ["DRAFT", "CONFIRMED", "COMPLETED"];
  const currentIndex = orderedStatuses.indexOf(status);
  const dateFor = (step: string): string | null =>
    step === "DRAFT"
      ? createdAt
      : step === "PENDING_APPROVAL"
        ? approval
          ? approvalDate(approval)
          : null
        : step === "CONFIRMED"
          ? confirmedAt
          : completedAt;

  // A rung the document has not reached carries no date: a rejected
  // draft or a document still waiting for its approval has nothing to
  // date there, whatever stamps the record holds.
  return orderedStatuses.map((step, index) => {
    const state =
      index < currentIndex
        ? ("complete" as const)
        : index === currentIndex
          ? ("current" as const)
          : ("upcoming" as const);
    return {
      key: step,
      date: state === "upcoming" ? null : dateFor(step),
      state,
    };
  });
}

export function DocumentStatusTimeline({
  status,
  createdAt,
  confirmedAt,
  completedAt,
  cancelledAt,
  approval,
  formatDate,
  isCorrection,
}: DocumentStatusTimelineProps) {
  const { t } = useTranslation("warehouse");
  // The drawing moved to the shared StatusTimeline so purchase orders could
  // have the same axis; the steps and their vocabulary stay here.
  const steps = buildTimelineSteps(
    status,
    createdAt,
    confirmedAt,
    completedAt,
    cancelledAt ?? null,
    approval,
    isCorrection,
  );

  return (
    <StatusTimeline
      title={t("detail.statusProgress")}
      steps={steps.map((step) => ({
        ...step,
        label: t(`status.${step.key}`),
      }))}
      formatDate={formatDate}
    />
  );
}
