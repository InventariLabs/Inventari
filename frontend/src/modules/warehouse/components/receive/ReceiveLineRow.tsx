import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { TypedSlot } from "@/components/Slot";
import type { RegisterBeforeSubmit } from "@/lib/moduleRegistry";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { unitLabel } from "@/lib/i18nHelpers";
import { ShelfSelect } from "@/modules/warehouse/components/LineTargetPicker";
import type { PutawayPreviewLine } from "@/modules/warehouse/api/putaway";
import { PutawayPlanSentence } from "./PutawayPlanSentence";
import { ReceiveLineHeld } from "./ReceiveLineHeld";
import { ReceiveLineProduct } from "./ReceiveLineProduct";
import { withModuleValues } from "@/modules/warehouse/components/documentFormShared";
import {
  draftLineView,
  isHeld,
  type ReceiveDraftLine,
  type RowPatch,
} from "./receiveDraft";

interface Props {
  line: ReceiveDraftLine;
  registerBeforeSubmit: RegisterBeforeSubmit;
  index: number;
  plan: PutawayPreviewLine | undefined;
  planChecking: boolean;
  showPrices: boolean;
  showTax: boolean;
  canWrite: boolean;
  /** The row a scan or paste just created: its count takes the focus. */
  focusLineKey: string | null;
  /** The order line behind this row arrived short, counted over its rows. */
  shortLine: boolean;
  /** The server refused the receipt until this row carries an expiry date. */
  needsExpiry: boolean;
  onFocusHandled: () => void;
  onUpdate: (key: string, patch: RowPatch) => void;
  onRemove: (key: string) => void;
  /** Enter in a count moves to the next row, or back to the scan field. */
  onQuantityEnter: (index: number) => void;
}

export function ReceiveLineRow({
  line,
  registerBeforeSubmit,
  index,
  plan,
  planChecking,
  showPrices,
  showTax,
  canWrite,
  focusLineKey,
  shortLine,
  needsExpiry,
  onFocusHandled,
  onUpdate,
  onRemove,
  onQuantityEnter,
}: Props) {
  const { t } = useTranslation("warehouse");
  const quantityRef = useRef<HTMLInputElement>(null);
  const hasDetails = Boolean(line.batchNumber || line.expiryDate);
  const [detailsOpen, setDetailsOpen] = useState(hasDetails);
  // A row that holds goods back shows it: the quantity is not a detail to hide.
  const [heldOpen, setHeldOpen] = useState(isHeld(line));

  // A pasted lot or expiry lands on a row that was already mounted with its
  // details folded; opening them lets the reader see what arrived instead of
  // trusting a collapsed row. A row the reader closed by hand stays closed
  // until the next arrival.
  useEffect(() => {
    if (hasDetails) setDetailsOpen(true);
  }, [hasDetails]);

  // The refusal names this row: its date field is where the answer goes.
  useEffect(() => {
    if (needsExpiry) setDetailsOpen(true);
  }, [needsExpiry]);

  useEffect(() => {
    if (focusLineKey !== line.key) return;
    quantityRef.current?.focus();
    quantityRef.current?.select();
    onFocusHandled();
  }, [focusLineKey, line.key, onFocusHandled]);

  const quantity = Number(line.quantity);
  const quantityInvalid = !Number.isFinite(quantity) || quantity <= 0;
  const expiryMissing = needsExpiry && !line.expiryDate;

  return (
    <>
      <tr className="border-t border-border align-top">
        <td className="px-4 py-2.5">
          <div className="flex flex-col gap-0.5">
            {/* As tall as the inputs beside it, so the name sits on their line. */}
            <div className="flex min-h-10 flex-col justify-center">
              <span className="text-sm font-semibold text-on">{line.name}</span>
              {(line.sku || line.barcode) && (
                <span className="text-xs text-on-secondary">
                  {line.sku || line.barcode}
                </span>
              )}
            </div>
            <ReceiveLineProduct
              line={line}
              canWrite={canWrite}
              onUpdate={onUpdate}
            />
            <Button
              type="button"
              variant="ghost"
              size="inline"
              className="self-start text-xs text-primary-600 hover:bg-transparent hover:underline"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((open) => !open)}
            >
              {t("receive.lotAndExpiry")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="inline"
              className="self-start text-xs text-primary-600 hover:bg-transparent hover:underline"
              aria-expanded={heldOpen}
              onClick={() => setHeldOpen((open) => !open)}
            >
              {t("receive.damagedOrOnHold")}
            </Button>
          </div>
        </td>
        <td className="whitespace-nowrap px-2 py-2.5 text-xs tabular-nums text-on-secondary">
          <div className="flex min-h-10 items-center">
            {line.ordered !== null
              ? `${line.ordered} ${unitLabel(t, line.uomSymbol)}`.trim()
              : "—"}
          </div>
        </td>
        <td className="px-2 py-2.5">
          <div className="flex w-32 items-center gap-1.5">
            <Input
              ref={quantityRef}
              type="text"
              inputMode="decimal"
              aria-label={t("receive.quantityLabel", { product: line.name })}
              aria-invalid={quantityInvalid || undefined}
              value={line.quantity}
              disabled={!canWrite}
              onChange={(event) =>
                onUpdate(line.key, { quantity: event.target.value })
              }
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                onQuantityEnter(index);
              }}
              wrapperClassName="w-20"
              className="text-right tabular-nums"
            />
            <span className="text-xs text-on-secondary">
              {unitLabel(t, line.uomSymbol)}
            </span>
          </div>
          {shortLine && (
            <span className="mt-1 block text-xs text-on-warning">
              {t("receive.shortLine")}
            </span>
          )}
        </td>
        <td className="min-w-80 px-2 py-2.5">
          <ShelfSelect
            value={line.targetLocationId}
            plannedId={plan?.planned_location_id}
            disabled={!canWrite}
            onChange={(target) =>
              onUpdate(line.key, { targetLocationId: target })
            }
            wrapperClassName="w-80"
          />
          <div className="mt-1 max-w-80 empty:hidden">
            <PutawayPlanSentence plan={plan} checking={planChecking} />
          </div>
        </td>
        {showPrices && (
          <td className="px-2 py-2.5">
            <div className="flex items-center gap-1.5">
              <Input
                type="text"
                inputMode="decimal"
                aria-label={t("receive.unitPriceLabel", { product: line.name })}
                value={line.unitPrice}
                disabled={!canWrite}
                onChange={(event) =>
                  onUpdate(line.key, { unitPrice: event.target.value })
                }
                wrapperClassName="w-24"
                className="text-right tabular-nums"
              />
              {showTax && (
                <Input
                  type="text"
                  inputMode="decimal"
                  aria-label={t("receive.vatLabel", { product: line.name })}
                  value={line.taxRate}
                  disabled={!canWrite}
                  onChange={(event) =>
                    onUpdate(line.key, { taxRate: event.target.value })
                  }
                  wrapperClassName="w-20"
                  className="text-right tabular-nums"
                />
              )}
            </div>
          </td>
        )}
        <td className="px-2 py-2.5 text-right">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("receive.removeLine", { product: line.name })}
            disabled={!canWrite}
            onClick={() => onRemove(line.key)}
          >
            <Trash2 size={16} />
          </Button>
        </td>
      </tr>
      {heldOpen && (
        <tr className="border-t border-border/60 bg-surface-inset/40">
          <td colSpan={showPrices ? 6 : 5} className="px-4 py-2">
            <ReceiveLineHeld
              line={line}
              canWrite={canWrite}
              onUpdate={onUpdate}
            />
          </td>
        </tr>
      )}
      {detailsOpen && (
        <tr className="border-t border-border/60 bg-surface-inset/40">
          <td colSpan={showPrices ? 6 : 5} className="px-4 py-2">
            <div className="flex flex-wrap items-end gap-3">
              <Input
                label={t("receive.lot")}
                value={line.batchNumber}
                disabled={!canWrite}
                onChange={(event) =>
                  onUpdate(line.key, { batchNumber: event.target.value })
                }
                wrapperClassName="w-48"
              />
              <DateInput
                label={t("receive.expiry")}
                value={line.expiryDate}
                disabled={!canWrite}
                error={expiryMissing ? t("receive.expiryNeeded") : undefined}
                onChange={(value) => onUpdate(line.key, { expiryDate: value })}
              />
              {expiryMissing && (
                <p className="pb-2 text-xs text-on-danger">
                  {t("receive.expiryNeeded")}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
      {/* Other modules' fields for this line, in a row of their own under
          the lot panel: a field about the lot (a certificate) placed in the
          product cell sat above the Lot it belongs to. The row hides itself
          while the slot draws nothing — a field that applies only once a lot
          is typed stays mounted, and so does its pre-submit check. */}
      <tr className="bg-surface-inset/40 has-[>td:empty]:hidden has-[.slot-container:empty]:hidden">
        <td colSpan={showPrices ? 6 : 5} className="px-4 py-2">
          <TypedSlot
            name="document_line_form_extra"
            className="max-w-md"
            data={{
              action: "receive",
              documentType: "IN",
              line: draftLineView(line),
              // Computed from the row as it stands when the write lands:
              // two modules writing at once each keep their own key.
              setMetaData: (module, values) =>
                onUpdate(line.key, (row) => ({
                  metaData: withModuleValues(row.metaData, module, values),
                })),
              registerBeforeSubmit,
            }}
          />
        </td>
      </tr>
    </>
  );
}
