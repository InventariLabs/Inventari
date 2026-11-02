import { useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { LineQuantityStepper } from "./LineQuantityStepper";
import {
  ReasonCodeField,
  reasonIsComplete,
} from "@/modules/shared/components/ReasonCodeField";
import {
  CORRECTION_REASON_CODES,
  type CorrectionReasonCode,
} from "@/modules/warehouse/reasonCodes";
import { useDiscardGuard } from "@/hooks/useDiscardGuard";
import { DiscardDraftDialog } from "@/components/ui/DiscardDraftDialog";
import { Sheet } from "@/components/ui/Sheet";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { useCreateCorrection } from "@/modules/warehouse/hooks/useDocuments";
import { useQuantityStepCheck } from "@/hooks/useUomPrecision";
import { formatQuantityValue } from "@/utils/formatters";

interface CorrectionLineDraft {
  original_line_number: number;
  line_name: string;
  original_quantity: number;
  quantity_delta: number;
  /** The line's unit — what the delta is counted in, and its step. */
  uom_id: string | null;
  notes: string;
}

interface CorrectionFormModalProps {
  document: WarehouseDocument;
  onClose: () => void;
}

export function CorrectionFormModal({
  document,
  onClose,
}: CorrectionFormModalProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  const navigate = useNavigate();

  const [generalNotes, setGeneralNotes] = useState("");
  const [reasonCode, setReasonCode] = useState<CorrectionReasonCode | "">("");
  const [triedToSubmit, setTriedToSubmit] = useState(false);
  const [lines, setLines] = useState<CorrectionLineDraft[]>(
    document.lines.map((line) => ({
      original_line_number: line.line_number ?? 1,
      line_name: line.name ?? line.barcode ?? `Line ${line.line_number ?? 1}`,
      original_quantity: Number(line.done_quantity ?? line.quantity ?? 0),
      quantity_delta: 0,
      uom_id: line.uom_id ?? null,
      notes: "",
    })),
  );

  const createMutation = useCreateCorrection();

  // A correction rewrites recorded history; the quantities and the reason the
  // reader has entered are work, so every exit asks before dropping them.
  const isDirty =
    reasonCode !== "" ||
    generalNotes.trim() !== "" ||
    lines.some((l) => l.quantity_delta !== 0 || l.notes.trim() !== "");
  const discard = useDiscardGuard(
    isDirty,
    onClose,
    t("warehouse:corrections.guardName"),
  );

  const updateDelta = (index: number, delta: number) => {
    // clearing the field to retype a number yields Number("") = NaN,
    // which survived Math.max, counted as a change, and was posted as null.
    const safeDelta = Number.isFinite(delta) ? delta : 0;
    setLines((prev) =>
      prev.map((line, i) =>
        i === index
          ? {
              ...line,
              // the negative side is bounded by the executed
              // quantity, mirroring the return window's Max: N clamp.
              quantity_delta: Math.max(-line.original_quantity, safeDelta),
            }
          : line,
      ),
    );
  };

  const updateLineNotes = (index: number, notes: string) => {
    setLines((prev) =>
      prev.map((line, i) => (i === index ? { ...line, notes } : line)),
    );
  };

  const changedLines = lines.filter((l) => l.quantity_delta !== 0);
  const hasChanges = changedLines.length > 0;
  // A delta the unit cannot hold is refused by the service and always was —
  // but the field showed it, the button stayed live, and the refusal arrived
  // after the click. The magnitude is what the unit measures: a delta is
  // signed by design.
  const stepCheck = useQuantityStepCheck();
  const offStepLine = changedLines.some(
    (line) =>
      stepCheck(Math.abs(line.quantity_delta), { uomId: line.uom_id }) !== "",
  );
  // a correction rewrites recorded history and lands in the register,
  // so an empty reason is worse than an empty rejection note — require it.
  // The code is what a report can count; the note carries the rest.
  const reasonComplete = reasonIsComplete(reasonCode, generalNotes);

  return (
    <Sheet
      open
      onClose={discard.requestClose}
      maxWidth="3xl"
      aria-label={t("corrections.createTitle")}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 sm:p-5 border-b border-border flex-shrink-0">
        <div>
          <h2 className="font-semibold text-on">
            {t("corrections.createTitle")}
          </h2>
          <p className="text-xs text-on-secondary mt-0.5 hidden sm:block">
            {t("corrections.createSubtitle", { number: document.number })}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={discard.requestClose}
          aria-label={t("common:actions.close")}
        >
          <X size={18} />
        </Button>
      </div>

      {/* Warning banner */}
      <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-800/50 dark:bg-amber-950/20 px-3 py-2.5">
        <AlertTriangle
          size={15}
          className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5"
        />
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {t("corrections.warning")}
        </p>
      </div>

      {/* Lines */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-3">
        {lines.map((line, index) => (
          <div
            key={line.original_line_number}
            className="rounded-xl border border-border bg-surface-raised p-3 space-y-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-on truncate">
                {line.line_name}
              </span>
              <span className="text-xs text-on-secondary shrink-0">
                {t("corrections.executed")}:{" "}
                {formatQuantityValue(line.original_quantity)}
              </span>
              <span className="text-xs text-on-secondary shrink-0">
                {t("corrections.minDelta", { max: line.original_quantity })}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-on-secondary w-14 shrink-0">
                {t("corrections.delta")}
              </span>
              <LineQuantityStepper
                value={line.quantity_delta}
                // A field holding no number is a delta of zero — the window's
                // own meaning for "cleared", not the field's.
                onChange={(next) => updateDelta(index, next ?? 0)}
                min={-line.original_quantity}
                uomId={line.uom_id}
                label={t("corrections.delta")}
                className={
                  line.quantity_delta < 0
                    ? "text-red-600 dark:text-red-400"
                    : line.quantity_delta > 0
                      ? "text-accent-600 dark:text-accent-400"
                      : ""
                }
              />
              {line.quantity_delta !== 0 && (
                <span
                  className={`text-xs font-medium ${
                    line.quantity_delta < 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-accent-600 dark:text-accent-400"
                  }`}
                >
                  {line.quantity_delta > 0 ? "+" : ""}
                  {line.quantity_delta}
                </span>
              )}
            </div>

            {line.quantity_delta !== 0 && (
              <Input
                aria-label={t("corrections.lineNotesPlaceholder")}
                placeholder={t("corrections.lineNotesPlaceholder")}
                value={line.notes}
                onChange={(e) => updateLineNotes(index, e.target.value)}
                className="text-xs h-7"
              />
            )}
          </div>
        ))}
      </div>

      {/* General notes + footer */}
      <div className="flex-shrink-0 border-t border-border p-4 sm:p-5 space-y-3">
        <ReasonCodeField
          testId="correction-reason"
          label={t("reasons.correction.label")}
          codes={CORRECTION_REASON_CODES}
          labelFor={(c) => t(`reasons.correction.codes.${c}`)}
          code={reasonCode}
          onCodeChange={setReasonCode}
          note={generalNotes}
          onNoteChange={setGeneralNotes}
          showErrors={triedToSubmit}
        />
        <div className="flex gap-2 justify-end">
          <Button variant="outline" onClick={discard.requestClose}>
            {t("common:form.cancel")}
          </Button>
          <Button
            onClick={() => {
              // The button no longer answers for the reason: it counts lines,
              // so a disabled one with "Create correction (2)" on it read as
              // "not enough lines". Pressing it now says what is missing.
              setTriedToSubmit(true);
              if (!reasonComplete || reasonCode === "") return;
              createMutation.mutate(
                {
                  corrects_document_id: document.id,
                  lines: lines
                    .filter((l) => l.quantity_delta !== 0)
                    .map((l) => ({
                      original_line_number: l.original_line_number,
                      quantity_delta: l.quantity_delta,
                      notes: l.notes || null,
                    })),
                  reason_code: reasonCode,
                  notes: generalNotes || null,
                },
                {
                  onSuccess: (correction) => {
                    toast.success(
                      t("corrections.created", {
                        number: correction.number,
                      }),
                    );
                    onClose();
                    navigate(`/warehouse/documents/${correction.id}`);
                  },
                  onError: (err: unknown) => {
                    // `err.message` on an axios error is "Request failed with
                    // status code 409" — the server's own sentence is in the
                    // response body, which is what extractApiError reads.
                    toast.error(
                      extractApiError(err, t("errors.correctionFailed")),
                    );
                  },
                },
              );
            }}
            disabled={!hasChanges || offStepLine || createMutation.isPending}
          >
            {createMutation.isPending
              ? t("corrections.creating")
              : t("corrections.createButton", {
                  count: changedLines.length,
                })}
          </Button>
        </div>
      </div>
      <DiscardDraftDialog {...discard.dialogProps} />
    </Sheet>
  );
}
