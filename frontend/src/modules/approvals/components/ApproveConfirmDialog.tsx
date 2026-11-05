import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { formatMoney } from "@/utils/formatters";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import { stageName } from "@/modules/approvals/workflowStages";

interface ApproveConfirmDialogProps {
  open: boolean;
  approval: ApprovalRequest;
  onConfirm: (notes?: string) => void;
  onCancel: () => void;
}

/**
 * The confirmation that stands in front of a single approval.
 *
 * It exists because approving is irreversible — it records the decision and,
 * for a document, either confirms it for warehouse execution (the stock moves
 * later, when someone runs the receipt) or, when the document was submitted
 * by the one-step action, posts its stock now. It names its target because a
 * confirmation that hides what it confirms asks for a decision the reader
 * cannot make: the dialog restates the facts the card shows and says what
 * this approval does to this request.
 */
export function ApproveConfirmDialog({
  open,
  approval,
  onConfirm,
  onCancel,
}: ApproveConfirmDialogProps) {
  const { t } = useTranslation("approvals");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!open) setNote("");
  }, [open]);

  const summary = approval.target_summary ?? null;
  const stages = approval.workflow_stages ?? [];

  const currentStage = stages.find(
    (stage) => stage.order === approval.current_stage,
  );
  const nextStage = stages.find(
    (stage) => stage.order > approval.current_stage,
  );

  const consequence = nextStage
    ? t("request.approveConfirmNextStage", {
        current: currentStage
          ? stageName(currentStage)
          : `#${approval.current_stage}`,
        next: stageName(nextStage),
      })
    : approval.target_type === "document"
      ? summary?.posts_on_approval
        ? t("request.approveConfirmFinalDocumentPosts")
        : t("request.approveConfirmFinalDocument")
      : t("request.approveConfirmFinal");

  const facts = [
    [
      summary?.type
        ? t(`dashboard.docTypes.${summary.type}`, {
            defaultValue: summary.type,
          })
        : null,
      summary?.lines_count != null
        ? t("dashboard.targetSummary.linesCount", {
            count: summary.lines_count,
          })
        : null,
      summary?.total_value
        ? t("dashboard.targetSummary.netAmount", {
            amount: formatMoney(summary.total_value, summary.currency ?? null),
          })
        : null,
    ]
      .filter(Boolean)
      .join(" · "),
    summary?.source_location_name && summary?.target_location_name
      ? t("dashboard.locationRoute", {
          from: summary.source_location_name,
          to: summary.target_location_name,
        })
      : null,
    summary?.partner_name ?? null,
  ].filter((line): line is string => Boolean(line));

  return (
    <ConfirmDialog
      open={open}
      title={
        summary?.number
          ? t("request.approveConfirmTitleNamed", { name: summary.number })
          : t("request.approveConfirmTitle")
      }
      message={consequence}
      confirmLabel={t("request.approveConfirmLabel")}
      cancelLabel={t("common:actions.cancel")}
      onConfirm={() => onConfirm(note.trim() || undefined)}
      onCancel={onCancel}
    >
      {facts.length > 0 && (
        <div className="rounded-md bg-surface-inset/60 px-3 py-2 text-sm text-on-secondary">
          {facts.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
      <Input
        label={t("request.approveNoteLabel")}
        placeholder={t("request.approveNotePlaceholder")}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
    </ConfirmDialog>
  );
}
