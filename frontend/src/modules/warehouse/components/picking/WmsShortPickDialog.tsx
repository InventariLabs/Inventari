import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet, SheetActions, SheetBody } from "@/components/ui/Sheet";
import { PICK_SHORTAGE_CODES } from "@/modules/warehouse/discrepancyCodes";
import type { WmsPickLine } from "@/modules/warehouse/api/documents";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface Props {
  line: WmsPickLine;
  isLoading: boolean;
  onConfirm: (
    lineId: string,
    pickedQty: number,
    code?: string,
    reason?: string,
    replaceScans?: boolean,
  ) => void;
  onCancel: () => void;
}

export default function WmsShortPickDialog({
  line,
  isLoading,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation("warehouse");
  // The line's final total, prefilled with what the scans already recorded:
  // a worker who scanned 7 of 10 sees 7 and corrects it to the number they
  // counted, instead of guessing whether the window wants 7, 3 or 10.
  const scanned = line.picked_quantity;
  const expected = line.expected_quantity;
  const remaining = Math.max(expected - scanned, 0);
  const [qty, setQty] = useState(String(scanned));
  const [replaceScans, setReplaceScans] = useState(false);
  const [code, setCode] = useState<string>(PICK_SHORTAGE_CODES[0]);
  const [note, setNote] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const unitSymbol = line.uom_symbol;

  const parsedQty = parseFloat(qty);
  // A total under the scans is allowed only when it says it replaces them:
  // the record must not quietly lose goods somebody already handled.
  const isBelowScanned = !isNaN(parsedQty) && parsedQty < scanned;
  const isValid =
    !isNaN(parsedQty) &&
    parsedQty > 0 &&
    parsedQty <= expected &&
    (!isBelowScanned || replaceScans);
  const isFullPick = parsedQty === expected;

  const confirm = () => {
    if (!isValid) {
      setValidationError(
        parsedQty > expected
          ? t("picking.qty_over_expected")
          : isBelowScanned
            ? t("picking.short_pick_below_scanned")
            : t("picking.qty_required"),
      );
      return;
    }
    if (!isFullPick && code === "OTHER" && note.trim() === "") {
      setValidationError(t("picking.discrepancy_note_required"));
      return;
    }
    // a full pick carries no discrepancy — nothing was wrong with the
    // line, so asking for a code forces a lie.
    onConfirm(
      line.id,
      parsedQty,
      isFullPick ? undefined : code,
      isFullPick ? undefined : note.trim() || undefined,
      isBelowScanned ? replaceScans : false,
    );
  };

  return (
    // The shared primitive, so this window is a dialog to a screen reader and
    // to the surface scanner the same way its receiving twin already is: role,
    // accessible name, focus trap and Escape all come from `Sheet`. It used to
    // be a bare `absolute inset-0` div, which announced nothing and left the
    // page underneath in the tab order.
    <Sheet
      open
      onClose={onCancel}
      zIndex="modal-nested"
      maxWidth="md"
      aria-labelledby="short-pick-title"
    >
      <SheetBody className="p-5">
        <div className="flex items-center gap-2">
          <AlertTriangle size={18} className="text-amber-500 shrink-0" />
          <h3 id="short-pick-title" className="text-base font-semibold text-on">
            {t("picking.short_pick_title")}
          </h3>
        </div>
        <p className="mt-1 text-sm text-on-secondary">
          {line.product_name ?? t("picking.unknown_product")}
        </p>
        <p className="mt-1 text-xs text-on-muted">
          {t("picking.short_pick_description", {
            expected: formatQuantityLocalized(t, expected, unitSymbol),
            scanned: formatQuantityLocalized(t, scanned, unitSymbol),
            remaining: formatQuantityLocalized(t, remaining, unitSymbol),
          })}
        </p>

        {validationError && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800/50 dark:bg-red-950/20 dark:text-red-300"
          >
            {validationError}
          </p>
        )}

        <div className="mt-4 space-y-3">
          <div>
            <label
              htmlFor="short-pick-qty"
              className="mb-1 block text-sm font-medium text-on"
            >
              {t("picking.short_pick_quantity")}
            </label>
            <QuantityInput
              id="short-pick-qty"
              uomSymbol={unitSymbol}
              min={0}
              max={expected}
              value={qty}
              onChange={(e) => {
                setQty(e.target.value);
                setValidationError(null);
              }}
              autoFocus
            />
          </div>
          {isBelowScanned && (
            <Checkbox
              id="short-pick-replace-scans"
              checked={replaceScans}
              onChange={(e) => {
                setReplaceScans(e.target.checked);
                setValidationError(null);
              }}
              label={t("picking.short_pick_replaces_scans")}
            />
          )}
          {!isFullPick && (
            /* The same question its receiving twin asks: why did the line
               come up short. The answer used to be hardcoded server-side —
               every short pick on record claimed SHORTAGE, including the
               damaged cartons. */
            <NativeSelect
              label={t("picking.discrepancy")}
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                setValidationError(null);
              }}
            >
              {PICK_SHORTAGE_CODES.map((c) => (
                <option key={c} value={c}>
                  {t(`detail.discrepancyCodes.${c}`)}
                </option>
              ))}
            </NativeSelect>
          )}
          {!isFullPick && code === "OTHER" && (
            <div>
              <label
                htmlFor="short-pick-note"
                className="mb-1 block text-sm font-medium text-on"
              >
                {t("picking.discrepancy_note")}
              </label>
              <Input
                id="short-pick-note"
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                  setValidationError(null);
                }}
                placeholder={t("picking.discrepancy_note_placeholder")}
              />
            </div>
          )}
        </div>

        {/* Skipping a line is the row's own action, with an icon beside the
            line it skips — the receiving twin retired this dialog's Skip for
            the same reason: two answers to one question. */}
        <SheetActions className="mt-5">
          <Button variant="ghost" onClick={onCancel} disabled={isLoading}>
            {t("common:form.cancel")}
          </Button>
          <Button onClick={confirm} disabled={isLoading}>
            {isLoading && <Loader2 size={14} className="animate-spin" />}
            {t("picking.confirm_short")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
