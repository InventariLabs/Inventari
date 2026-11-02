import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useQuantityStepCheck, useUomPrecision } from "@/hooks/useUomPrecision";
import { formatQuantity, formatQuantityValue } from "@/utils/formatters";
import {
  CONSUMPTION_REASONS,
  reasonLabelKey,
} from "@/modules/inventory/constants/stockReasons";
import type { Item } from "@/types";
import { unitLabel } from "@/lib/i18nHelpers";

interface ConsumeDialogProps {
  open: boolean;
  item: Item | null;
  /**
   * Returning a promise keeps the dialog open until the change settles, and
   * keeps the quantity and reason as typed when it fails — see ConfirmDialog.
   */
  onConfirm: (quantity: number, reason: string, notes?: string) => unknown;
  onCancel: () => void;
}

export function ConsumeDialog({
  open,
  item,
  onConfirm,
  onCancel,
}: ConsumeDialogProps) {
  const { t } = useTranslation(["items", "common"]);
  // "" is the cleared field, a state every manual entry passes through — the
  // same bargain DefaultServingsField strikes. Bounds are applied where the
  // request is made, not at the typing event.
  const [quantity, setQuantity] = useState<number | "">(1);
  const [reason, setReason] = useState("USED");
  const [notes, setNotes] = useState("");
  // The unit's own step is the smallest amount that can leave a shelf: 1 for
  // a piece, 0.001 for a gram. This dialog used a floor of one whole unit for
  // every unit of measure, so half a kilogram could not be taken off — 0.5
  // was raised to 1 without a word and a whole kilogram left the shelf.
  const precision = useUomPrecision(item?.uom_id);
  const stepCheck = useQuantityStepCheck();

  if (!item) return null;

  // "Other" is the one answer that says nothing on its own. The note is what
  // makes it an answer, so it is asked for and required — the same bargain
  // the delete dialog already strikes.
  const needsNote = reason === "OTHER";
  const canConfirm = !needsNote || notes.trim() !== "";

  const available = Number(item.quantity);
  const maxQuantity = Math.max(available, precision.min);
  // What the reader typed, never a number quietly put in its place. A value
  // the shelf cannot honour is said out loud and the button stops offering
  // to send it; the old code took min(max(requested, 1), max) and sent the
  // result, so "0,5" left the screen as 1.
  const requested = typeof quantity === "number" ? quantity : NaN;
  // Below the step and off the step are the unit's own verdicts, and the
  // field says them itself; what is left for this dialog is its own bound —
  // there is only so much on the shelf.
  const unitError = stepCheck(quantity, { uomId: item.uom_id });
  const aboveAvailable = Number.isFinite(requested) && requested > maxQuantity;
  const rangeError = aboveAvailable
    ? t("items:consumeDialog.aboveAvailable", {
        max: formatQuantityValue(maxQuantity, item.uom?.rounding),
      })
    : "";
  const quantityReady =
    Number.isFinite(requested) && !aboveAvailable && unitError === "";

  const handleConfirm = () => {
    return onConfirm(requested, reason, notes.trim() || undefined);
  };

  return (
    <ConfirmDialog
      open={open}
      title={t("items:consumeDialog.title")}
      message={t("items:consumeDialog.description", {
        name: item.name,
        // The wire sends a quantity as exact text ("6.600"), and i18next
        // interpolates a string as it stands — so a Polish sentence carried
        // an English decimal point and the unit's trailing zeros. The unit's
        // word goes through the resolver for the same reason.
        quantity: formatQuantityValue(item.quantity, item.uom?.rounding),
        uom: unitLabel(t, item.uom?.symbol),
      })}
      confirmLabel={
        // The button names the amount that will leave — the one that was
        // typed, since nothing is substituted for it any more. With the
        // field empty there is no amount to name, and a button reading
        // "Remove 0" would be naming one.
        Number.isFinite(requested)
          ? t("items:consumeDialog.confirmAmount", {
              quantity: formatQuantity(
                requested,
                unitLabel(t, item.uom?.symbol),
                item.uom?.rounding,
              ),
            })
          : t("items:consumeDialog.confirmNoAmount")
      }
      cancelLabel={t("common:actions.cancel")}
      variant="warning"
      confirmDisabled={!canConfirm || !quantityReady}
      onConfirm={handleConfirm}
      onCancel={onCancel}
    >
      <div className="space-y-3">
        <QuantityInput
          label={t("items:consumeDialog.quantityLabel")}
          uomId={item.uom_id}
          max={maxQuantity}
          value={quantity}
          error={rangeError}
          onChange={(e) => {
            const next = e.target.value.trim();
            const parsed = Number(next);
            setQuantity(next === "" || Number.isNaN(parsed) ? "" : parsed);
          }}
        />
        <NativeSelect
          label={t("items:consumeDialog.reasonLabel")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        >
          {CONSUMPTION_REASONS.map((value) => (
            <option key={value} value={value}>
              {t(reasonLabelKey(value))}
            </option>
          ))}
        </NativeSelect>
        {needsNote && (
          <Input
            label={t("items:consumeDialog.notesLabel")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t("items:consumeDialog.notesPlaceholder")}
            data-testid="consume-notes"
            autoFocus
          />
        )}
      </div>
    </ConfirmDialog>
  );
}
