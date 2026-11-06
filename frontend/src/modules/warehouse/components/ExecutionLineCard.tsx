import { memo } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { QuantityInput } from "@/components/ui/QuantityInput";
import {
  DOCUMENT_DISCREPANCY_CODES,
  DOCUMENT_HELD_CODES,
} from "@/modules/warehouse/discrepancyCodes";
import { getDocumentLineStatusVariant } from "@/modules/warehouse/lineStatus";
import { unitLabel } from "@/lib/i18nHelpers";
import { formatQuantityValue } from "@/utils/formatters";
import { typedDoneQuantity } from "@/modules/warehouse/hooks/useDocumentExecution";
import type {
  DocumentDiscrepancyCode,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import type { TFunction } from "i18next";

interface ExecutionLineCardProps {
  line: WarehouseDocument["lines"][number];
  documentStatus: string;
  currentDoneQuantity: number;
  /** A receipt can hold part of what it received back; a dispatch cannot. */
  isReceipt: boolean;
  requiresDiscrepancy: boolean;
  isActiveScanLine: boolean;
  lastScannedLineId: string | null;
  isReasonEditorOpen: boolean;
  executionLineStatus: "PENDING" | "DONE" | "PARTIAL" | "EXCEPTION";
  values: Record<string, string>;
  heldValues: Record<string, string>;
  codes: Record<string, DocumentDiscrepancyCode | "">;
  codeError?: string;
  reasons: Record<string, string>;
  onUpdateDoneQuantity: (lineId: string, qty: number) => void;
  onHeldChange: (lineId: string, qty: number) => void;
  onCodeChange: (lineId: string, code: DocumentDiscrepancyCode | "") => void;
  onReasonToggle: (lineId: string) => void;
  onReasonChange: (lineId: string, reason: string) => void;
  t: TFunction;
}

interface LineQuantityControlsProps extends Pick<
  ExecutionLineCardProps,
  | "line"
  | "currentDoneQuantity"
  | "isReceipt"
  | "requiresDiscrepancy"
  | "isActiveScanLine"
  | "isReasonEditorOpen"
  | "heldValues"
  | "codes"
  | "codeError"
  | "reasons"
  | "onUpdateDoneQuantity"
  | "onHeldChange"
  | "onCodeChange"
  | "onReasonToggle"
  | "onReasonChange"
  | "t"
> {
  expectedQuantity: number;
}

/**
 * The fields under the quantity: what is quarantined, the quick buttons and
 * the reason a line is short. Its own component because together they carry
 * more branches than the card around them is allowed to hold.
 */
function LineQuantityControls({
  line,
  currentDoneQuantity,
  expectedQuantity,
  isReceipt,
  requiresDiscrepancy,
  isActiveScanLine,
  isReasonEditorOpen,
  heldValues,
  codes,
  codeError,
  reasons,
  onUpdateDoneQuantity,
  onHeldChange,
  onCodeChange,
  onReasonToggle,
  onReasonChange,
  t,
}: LineQuantityControlsProps) {
  const heldQuantity = Number(heldValues[line.id] ?? "0") || 0;
  // A held quantity is a reason in itself, so the code shows even when the
  // line is not short; with none held, only a short line has something to
  // explain.
  const showsCode = requiresDiscrepancy || heldQuantity > 0;
  const codeChoices =
    heldQuantity > 0 ? DOCUMENT_HELD_CODES : DOCUMENT_DISCREPANCY_CODES;

  return (
    <>
      {isReceipt && (
        <QuantityInput
          id={`held-quantity-${line.id}`}
          uomId={line.uom_id}
          inputMode="decimal"
          min={0}
          max={String(currentDoneQuantity)}
          label={t("warehouse:detail.heldQuantityLabel")}
          value={heldValues[line.id] ?? "0"}
          onQuantityChange={(quantity) => {
            if (quantity !== null) onHeldChange(line.id, quantity);
          }}
        />
      )}

      <div
        className={
          isActiveScanLine
            ? "grid grid-cols-2 gap-2 sm:flex sm:flex-wrap"
            : "grid grid-cols-3 gap-2 sm:flex sm:flex-wrap"
        }
      >
        <Button
          type="button"
          variant={isActiveScanLine ? "primary" : "outline"}
          size={isActiveScanLine ? "md" : "sm"}
          className="w-full"
          onClick={() => onUpdateDoneQuantity(line.id, currentDoneQuantity + 1)}
        >
          {t("warehouse:detail.quickIncrement")}
        </Button>
        <Button
          type="button"
          variant={isActiveScanLine ? "success" : "outline"}
          size={isActiveScanLine ? "md" : "sm"}
          className="w-full"
          onClick={() => onUpdateDoneQuantity(line.id, expectedQuantity)}
        >
          {t("warehouse:detail.quickFillRemaining")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={isActiveScanLine ? "col-span-2 w-full" : "w-full"}
          onClick={() => onUpdateDoneQuantity(line.id, 0)}
        >
          {t("warehouse:detail.quickClear")}
        </Button>
      </div>

      {showsCode && (
        <>
          <NativeSelect
            id={`discrepancy-code-${line.id}`}
            label={t("warehouse:detail.discrepancyCodeLabel")}
            value={codes[line.id] ?? ""}
            error={codeError}
            onChange={(event) => {
              onCodeChange(
                line.id,
                event.target.value as DocumentDiscrepancyCode | "",
              );
            }}
          >
            <option value="">
              {t("warehouse:detail.discrepancyCodePlaceholder")}
            </option>
            {codeChoices.map((code) => (
              <option key={code} value={code}>
                {t(`detail.discrepancyCodes.${code}`)}
              </option>
            ))}
          </NativeSelect>
          <Button
            type="button"
            variant={isReasonEditorOpen ? "outline" : "ghost"}
            size="sm"
            className="self-start"
            onClick={() => onReasonToggle(line.id)}
          >
            {isReasonEditorOpen
              ? t("warehouse:detail.discrepancyReasonHide")
              : t("warehouse:detail.discrepancyReasonAdd")}
          </Button>
          {isReasonEditorOpen && (
            <Input
              id={`discrepancy-reason-${line.id}`}
              type="text"
              label={t("warehouse:detail.discrepancyReasonLabel")}
              placeholder={t("warehouse:detail.discrepancyReasonPlaceholder")}
              value={reasons[line.id] ?? ""}
              onChange={(event) => {
                onReasonChange(line.id, event.target.value);
              }}
            />
          )}
        </>
      )}
    </>
  );
}

const ExecutionLineCard = memo(function ExecutionLineCard({
  line,
  documentStatus: _documentStatus,
  currentDoneQuantity,
  isReceipt,
  requiresDiscrepancy,
  isActiveScanLine,
  lastScannedLineId,
  isReasonEditorOpen,
  executionLineStatus,
  values,
  heldValues,
  codes,
  codeError,
  reasons,
  onUpdateDoneQuantity,
  onHeldChange,
  onCodeChange,
  onReasonToggle,
  onReasonChange,
  t,
}: ExecutionLineCardProps) {
  const expectedQuantity = Number(line.expected_quantity ?? line.quantity);
  const remainingQuantity = Math.max(expectedQuantity - currentDoneQuantity, 0);
  // A hand-typed line carries no unit, and the sentence has a slot for one.
  // Filling it with a dash said "5 -"; leaving it empty said "5 ·", and both
  // are a number the panel cannot back with a unit. The no-unit sentence
  // names the absence instead of printing a quantity dressed as a measurement.
  const unit = unitLabel(t, line.uom?.symbol ?? "");

  return (
    <div
      data-testid={`document-line-card-${line.id}`}
      data-active-scan-target={isActiveScanLine ? "true" : "false"}
      className={
        isActiveScanLine
          ? "rounded-xl border border-primary-400 bg-primary-50/60 p-4 space-y-3 shadow-sm shadow-primary-100"
          : lastScannedLineId === line.id
            ? "rounded-xl border border-primary-300 bg-primary-50/40 p-4 space-y-3"
            : "rounded-xl border border-border bg-surface-card p-4 space-y-3"
      }
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              {t("warehouse:detail.lineCardNumber", {
                number: line.line_number,
              })}
            </Badge>
            <Badge variant={getDocumentLineStatusVariant(executionLineStatus)}>
              {t(`detail.lineStatuses.${executionLineStatus}`)}
            </Badge>
            {isActiveScanLine && (
              <Badge variant="default">
                {t("warehouse:detail.scanActiveLine")}
              </Badge>
            )}
          </div>
          <p className="text-sm font-medium text-on">{line.name ?? "—"}</p>
          <p className="text-xs text-on-secondary">
            {unit
              ? t("warehouse:detail.executionMeta", {
                  expected: formatQuantityValue(expectedQuantity),
                  remaining: formatQuantityValue(remainingQuantity),
                  unit,
                })
              : t("warehouse:detail.executionMetaNoUnit", {
                  expected: formatQuantityValue(expectedQuantity),
                  remaining: formatQuantityValue(remainingQuantity),
                })}
          </p>
        </div>
        {lastScannedLineId === line.id && (
          <span className="inline-flex items-center rounded-full bg-primary-100 px-2 py-1 text-xs font-medium uppercase tracking-wide text-primary-800">
            {t("warehouse:detail.scanRecentlyScanned")}
          </span>
        )}
      </div>

      <QuantityInput
        id={`done-quantity-${line.id}`}
        uomId={line.uom_id}
        inputMode="decimal"
        // Nothing received yet is this field's resting state, and it is what
        // "Clear" puts back; the unit's own floor would call every line of a
        // freshly confirmed document invalid before anyone touched it.
        min={0}
        max={String(expectedQuantity)}
        label={t("warehouse:detail.doneQuantityLabel")}
        value={typedDoneQuantity(values, line.id)}
        onQuantityChange={(quantity) => {
          if (quantity !== null) onUpdateDoneQuantity(line.id, quantity);
        }}
      />

      <LineQuantityControls
        line={line}
        currentDoneQuantity={currentDoneQuantity}
        expectedQuantity={expectedQuantity}
        isReceipt={isReceipt}
        requiresDiscrepancy={requiresDiscrepancy}
        isActiveScanLine={isActiveScanLine}
        isReasonEditorOpen={isReasonEditorOpen}
        heldValues={heldValues}
        codes={codes}
        codeError={codeError}
        reasons={reasons}
        onUpdateDoneQuantity={onUpdateDoneQuantity}
        onHeldChange={onHeldChange}
        onCodeChange={onCodeChange}
        onReasonToggle={onReasonToggle}
        onReasonChange={onReasonChange}
        t={t}
      />
    </div>
  );
});

export { ExecutionLineCard };
