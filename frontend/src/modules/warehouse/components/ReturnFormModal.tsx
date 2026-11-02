import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { LineQuantityStepper } from "./LineQuantityStepper";
import { useDiscardGuard } from "@/hooks/useDiscardGuard";
import { DiscardDraftDialog } from "@/components/ui/DiscardDraftDialog";
import { Sheet } from "@/components/ui/Sheet";
import {
  ReasonCodeField,
  reasonIsComplete,
} from "@/modules/shared/components/ReasonCodeField";
import {
  RETURN_REASON_CODES,
  type ReturnReasonCode,
} from "@/modules/warehouse/reasonCodes";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { useCreateReturn } from "@/modules/warehouse/hooks/useDocuments";
import { useQuantityStepCheck } from "@/hooks/useUomPrecision";
import { formatQuantityValue } from "@/utils/formatters";

interface ReturnLineDraft {
  original_line_number: number;
  line_name: string;
  done_quantity: number;
  return_quantity: number;
  /** The line's unit — what the quantity is counted in, and its step. */
  uom_id: string | null;
  reason: string;
}

interface ReturnFormModalProps {
  document: WarehouseDocument;
  onClose: () => void;
}

/** Which document type a return of this document creates (backend's map). */
const RETURN_TYPE_OF: Record<string, string> = {
  IN: "OUT",
  OUT: "IN",
  INT: "INT",
};

export function ReturnFormModal({ document, onClose }: ReturnFormModalProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  // The warning used to name a receipt (IN) whatever the source was, so a
  // return of an internal transfer promised a document type it never created.
  const returnType = RETURN_TYPE_OF[document.type] ?? document.type;
  const navigate = useNavigate();
  const createReturn = useCreateReturn();

  const [generalNotes, setGeneralNotes] = useState("");
  const [reasonCode, setReasonCode] = useState<ReturnReasonCode | "">("");
  const [triedToSubmit, setTriedToSubmit] = useState(false);
  const [lines, setLines] = useState<ReturnLineDraft[]>(
    document.lines.map((line) => ({
      original_line_number: line.line_number ?? 1,
      line_name: line.name ?? line.barcode ?? `Line ${line.line_number ?? 1}`,
      done_quantity: Number(line.done_quantity ?? line.quantity ?? 0),
      return_quantity: 0,
      uom_id: line.uom_id ?? null,
      reason: "",
    })),
  );

  // The quantities and the reason the reader has entered are work, so every
  // exit asks before dropping them.
  const isDirty =
    reasonCode !== "" ||
    generalNotes.trim() !== "" ||
    lines.some((l) => l.return_quantity !== 0 || l.reason.trim() !== "");
  const discard = useDiscardGuard(
    isDirty,
    onClose,
    t("warehouse:returns.guardName"),
  );

  const updateQuantity = (index: number, value: number) => {
    const max = lines[index].done_quantity;
    // An empty field is Number("") = NaN, and Math.min(max, NaN) is NaN — the
    // same hole the correction form had.
    const clamped = Math.max(
      0,
      Math.min(max, Number.isFinite(value) ? value : 0),
    );
    setLines((prev) =>
      prev.map((line, i) =>
        i === index ? { ...line, return_quantity: clamped } : line,
      ),
    );
  };

  const updateReason = (index: number, reason: string) => {
    setLines((prev) =>
      prev.map((line, i) => (i === index ? { ...line, reason } : line)),
    );
  };

  const activeLines = lines.filter((l) => l.return_quantity > 0);
  const hasSelection = activeLines.length > 0;
  // A quantity the unit cannot hold is refused by the service; the button
  // stops offering to send it.
  const stepCheck = useQuantityStepCheck();
  const offStepLine = activeLines.some(
    (line) => stepCheck(line.return_quantity, { uomId: line.uom_id }) !== "",
  );

  const handleSubmit = () => {
    if (!hasSelection) return;
    // Saying what is missing beats a button that will not press: the count on
    // it is a count of lines, so a disabled one reads as "pick more lines".
    setTriedToSubmit(true);
    if (!reasonIsComplete(reasonCode, generalNotes) || reasonCode === "")
      return;

    createReturn.mutate(
      {
        documentId: document.id,
        data: {
          lines: activeLines.map((l) => ({
            original_line_number: l.original_line_number,
            return_quantity: l.return_quantity,
            reason: l.reason || null,
          })),
          reason_code: reasonCode,
          notes: generalNotes || null,
        },
      },
      {
        onSuccess: (returnDoc) => {
          toast.success(
            t("returns.created", { number: documentTitle(t, returnDoc) }),
          );
          onClose();
          navigate(`/warehouse/documents/${returnDoc.id}`);
        },
        onError: (err: unknown) => {
          // A generic toast hid rules the server states plainly ("return
          // exceeds the executed quantity").
          toast.error(extractApiError(err, t("errors.returnFailed")));
        },
      },
    );
  };

  return (
    <Sheet
      open
      onClose={discard.requestClose}
      maxWidth="3xl"
      aria-label={t("returns.createTitle")}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 sm:p-5 border-b border-border flex-shrink-0">
        <div>
          <h2 className="font-semibold text-on">{t("returns.createTitle")}</h2>
          <p className="text-xs text-on-secondary mt-0.5 hidden sm:block">
            {t("returns.createSubtitle", {
              number: documentTitle(t, document),
            })}
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
          {t("returns.warningTyped", {
            type: t(`typesShort.${returnType}`, { defaultValue: returnType }),
          })}
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
                {t("returns.maxQuantity", { max: line.done_quantity })}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-on-secondary w-24 shrink-0">
                {t("returns.lineQuantity")}
              </span>
              <LineQuantityStepper
                value={line.return_quantity}
                // A field holding no number returns nothing of the line —
                // the window's own meaning for "cleared", not the field's.
                onChange={(next) => updateQuantity(index, next ?? 0)}
                min={0}
                max={line.done_quantity}
                uomId={line.uom_id}
                label={t("returns.lineQuantity")}
                className={
                  line.return_quantity > 0
                    ? "text-accent-600 dark:text-accent-400"
                    : ""
                }
              />
              {line.return_quantity > 0 && (
                <span className="text-xs text-on-secondary">
                  / {formatQuantityValue(line.done_quantity)}
                </span>
              )}
            </div>

            {line.return_quantity > 0 && (
              <Input
                aria-label={t("returns.reasonPlaceholder")}
                placeholder={t("returns.reasonPlaceholder")}
                value={line.reason}
                onChange={(e) => updateReason(index, e.target.value)}
                className="text-xs h-7"
              />
            )}
          </div>
        ))}
      </div>

      {/* General notes + footer */}
      <div className="flex-shrink-0 border-t border-border p-4 sm:p-5 space-y-3">
        <ReasonCodeField
          testId="return-reason"
          label={t("reasons.return.label")}
          codes={RETURN_REASON_CODES}
          labelFor={(c) => t(`reasons.return.codes.${c}`)}
          code={reasonCode}
          onCodeChange={setReasonCode}
          note={generalNotes}
          onNoteChange={setGeneralNotes}
          showErrors={triedToSubmit}
        />
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={discard.requestClose}>
            {t("common:form.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!hasSelection || offStepLine || createReturn.isPending}
          >
            {createReturn.isPending
              ? t("returns.creating")
              : t("returns.createButton", { count: activeLines.length })}
          </Button>
        </div>
      </div>
      <DiscardDraftDialog {...discard.dialogProps} />
    </Sheet>
  );
}
