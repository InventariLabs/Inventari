import { useTranslation } from "react-i18next";
import {
  StatusTimeline,
  type StatusTimelineStep,
} from "@/components/ui/StatusTimeline";
import type { PurchaseOrder } from "../types/purchase-orders";

/**
 * What the ladder needs to know about an approval, and no more.
 *
 * Structural on purpose: the approvals module's own request type fits
 * this shape, so the caller can pass one straight in without this
 * module reaching across the boundary for a type it reads four fields of.
 */
export interface POApprovalTrace {
  status: string;
  created_at: string;
  decisions: { status: string; decided_at?: string | null }[];
}

interface POStatusTimelineProps {
  po: PurchaseOrder;
  /**
   * The order's own approval request, whatever became of it, or null when
   * there never was one.
   */
  approval?: POApprovalTrace | null;
  formatDate: (dateStr: string | null) => string;
}

/**
 * Where an order stands: Draft → Confirmed → Completed, with the approval
 * stop shown for every order that went through one.
 *
 * The document detail has carried this axis for a long time; the order detail
 * showed a badge and nothing else, so the same information took two shapes in
 * two screens of the same product.
 *
 * The rungs come from what the order went through, not from where it is now.
 * Built from the current status, the ladder grew an approval rung while the
 * order waited and dropped it the moment the decision came in — so the one
 * card that could show an order had been approved stopped showing it exactly
 * when that became a fact about the past. A ladder is a history; a history
 * that forgets is a badge with extra dots.
 */
function approvalDate(approval: POApprovalTrace): string | null {
  // When it was decided, or failing that when it was asked for. The last
  // approving decision is the one that let the order through: earlier stages
  // only passed it on.
  const approved = approval.decisions
    .filter((d) => d.status === "APPROVED" && d.decided_at)
    .map((d) => d.decided_at as string)
    .sort();
  return approved[approved.length - 1] ?? approval.created_at ?? null;
}

function buildSteps(
  po: PurchaseOrder,
  approval: POApprovalTrace | null | undefined,
): Omit<StatusTimelineStep, "label">[] {
  // A request the order raised — including one already decided. `CANCELLED`
  // is a withdrawn request: the order never passed through that rung.
  const wentThroughApproval =
    po.status === "PENDING_APPROVAL" ||
    (approval != null && approval.status !== "CANCELLED");

  if (po.status === "CANCELLED") {
    return [
      { key: "DRAFT", date: po.created_at, state: "complete" },
      ...(wentThroughApproval && approval
        ? [
            {
              key: "PENDING_APPROVAL",
              date: approvalDate(approval),
              state: "complete" as const,
            },
          ]
        : []),
      { key: "CANCELLED", date: po.cancelled_at ?? null, state: "current" },
    ];
  }

  const ordered: string[] = wentThroughApproval
    ? ["DRAFT", "PENDING_APPROVAL", "CONFIRMED", "COMPLETED"]
    : ["DRAFT", "CONFIRMED", "COMPLETED"];
  const currentIndex = ordered.indexOf(po.status);
  const dateFor = (status: string) =>
    status === "DRAFT"
      ? po.created_at
      : status === "PENDING_APPROVAL"
        ? approval
          ? approvalDate(approval)
          : null
        : status === "CONFIRMED"
          ? (po.confirmed_at ?? null)
          : null;

  return ordered.map((status, index) => ({
    key: status,
    date: dateFor(status),
    state:
      index < currentIndex
        ? "complete"
        : index === currentIndex
          ? "current"
          : "upcoming",
  }));
}

export function POStatusTimeline({
  po,
  approval,
  formatDate,
}: POStatusTimelineProps) {
  const { t } = useTranslation("purchase_orders");

  return (
    <StatusTimeline
      title={t("detail.statusProgress")}
      steps={buildSteps(po, approval).map((step) => ({
        ...step,
        label: t(`status.${step.key}`),
      }))}
      formatDate={formatDate}
    />
  );
}
