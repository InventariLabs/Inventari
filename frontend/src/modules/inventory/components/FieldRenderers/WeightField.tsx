import { useId } from "react";
import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { QUANTITY_STEP } from "@/hooks/useUomPrecision";
import { findUom, useUoms } from "@/modules/shared/hooks/useUoms";
import { unitLabel } from "@/lib/i18nHelpers";
import { formatQuantity } from "@/utils/formatters";
import type { FieldDefinition, Uom } from "@/types";
import { getPlaceholder, getLabel } from "./helpers";
import { makeTDynamic } from "@/lib/i18nHelpers";

interface WeightFieldProps {
  /** Id the surrounding label points at — lands on the amount input. */
  id?: string;
  field: FieldDefinition;
  /** Weight of a single unit, as recorded on the product template. */
  value: unknown;
  weightUomId?: string;
  /** How many units this line holds — used for the informational total. */
  quantity?: unknown;
  error?: string;
  onChange: (value: unknown) => void;
  onUomChange: (uomId: string) => void;
}

/**
 * Weight — or volume — of one unit of the product, with its unit picked
 * explicitly.
 *
 * Volume belongs here as much as weight: a 1.5 l bottle counted in pieces has
 * no other place to record what one piece holds, and locking the picker to
 * the Weight category left drinks unrecordable. The stored total treats both
 * the same way, in thousandths of the reference unit — see
 * ``app.services.items.weight``.
 *
 * Precision is the unit's own knowledge, not this field's: the total keeps
 * the unit's rounding step, so an input finer than two places reads finer
 * instead of being silently clipped to what the old two-decimal cap
 * allowed. Every unit this picker offers — the Weight and Volume
 * categories, g through gal — keeps three places, so three is what a total
 * here shows; the sentence used to illustrate itself with a centimetre,
 * which is in Length and unreachable from this field.
 *
 * Until a unit is picked there is no unit to ask, and the screen must not
 * invent an answer either: it fell back to printing whatever decimals the
 * input carried, so 2 × 1.23456 read "2,4691" — four places, finer than any
 * unit in the picker allows. Without a unit the total keeps the quantity
 * columns' own scale, the floor every other consumer of a step already uses.
 *
 * One ceiling stands above all of this and is not the unit's: the formatter
 * trims to four decimal places before a step is applied at all. No unit in
 * the catalogue is finer than 0.001, so nothing reaches it today.
 *
 * The value belongs to the product template, not to this line (ADR-015); the
 * line's total is shown underneath as a read-only consequence of quantity ×
 * unit weight, which is exactly what the API computes.
 */
export function WeightField({
  id,
  field,
  value,
  weightUomId,
  quantity,
  error,
  onChange,
  onUomChange,
}: WeightFieldProps) {
  const { t } = useTranslation(["items", "common"]);
  const tDyn = makeTDynamic(t);

  const { data: uomCategories } = useUoms();

  const perUnit = parseFloat(String(value ?? ""));
  const qty = parseFloat(String(quantity ?? ""));
  const showTotal = !isNaN(perUnit) && !isNaN(qty) && qty > 1;

  // The total is grams for a weight and millilitres for a volume; without the
  // symbol the reader has to guess which, and half the time guesses wrong.
  const weightUom = findUom(uomCategories, weightUomId);
  const weightUomSymbol = unitLabel(t, weightUom?.symbol);
  // What to enter and what it adds up to describe the input itself.
  const hintId = useId();
  const totalId = useId();

  return (
    <div>
      <div className="flex items-stretch gap-2">
        <div className="flex-1">
          <Input
            id={id}
            type="number"
            inputMode="decimal"
            step="any"
            value={String(value ?? "")}
            // Named from the same source as the visible label the parent
            // renders (`getLabel`), not left to the id/htmlFor pairing alone.
            aria-label={getLabel(field, tDyn)}
            aria-describedby={showTotal ? `${hintId} ${totalId}` : hintId}
            onChange={(e) => {
              const raw = e.target.value;
              onChange(raw === "" ? null : raw.replace(",", "."));
            }}
            placeholder={getPlaceholder(field, undefined, tDyn)}
            className={error ? "border-red-300 bg-red-50" : ""}
          />
        </div>
        <div className="w-28 self-stretch">
          <UomSelect
            compact
            value={weightUomId || null}
            categoryFilter={["Weight", "Volume"]}
            onChange={(uomId: string, _uom: Uom) => onUomChange(uomId)}
          />
        </div>
      </div>

      <p
        id={hintId}
        className="text-xs text-on-muted mt-1.5 flex items-center gap-1.5 font-medium"
      >
        <Info size={12} className="text-primary-400" />
        {t("items:weightPerPieceHint")}
      </p>

      {showTotal && (
        <p id={totalId} className="text-xs text-on-muted mt-0.5 font-medium">
          {/* The product is a number the formatter reads directly; the unit's
              own step decides how many decimals it keeps — and with no unit
              picked, the quantity columns' scale does, rather than the
              accident of how many decimals were typed. */}
          {t("items:weightTotalHint", {
            total: formatQuantity(
              perUnit * qty,
              weightUomSymbol,
              weightUom?.rounding ?? QUANTITY_STEP,
            ),
          })}
        </p>
      )}
    </div>
  );
}
