import { Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { useUomPrecision } from "@/hooks/useUomPrecision";

interface Props {
  value: number;
  /**
   * The number the field holds, or null while it holds none — a cleared
   * field and every incomplete step of a fraction being typed both report
   * null. Each window decides what that means: the correction
   * and return windows read it as zero, a window that requires the number
   * ignores it and waits.
   */
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  /** The line's unit — it decides the step, not this component. */
  uomId?: string | null;
  /** Names the field, and the two buttons through it. */
  label: string;
  /** Tone applied to the number, decided by the caller's own arithmetic. */
  className?: string;
}

/**
 * How many units of a document line a window is talking about.
 *
 * The correction window drew a stepper with −/+ and the return window a bare
 * number field, for the same concept in two dialogs a reader opens from the
 * same menu. One control, one behaviour: the buttons obey the same bounds
 * typing does.
 *
 * The bound that matters most is the unit's own step. This stepper hardcoded
 * `step={1}`, which is decoration in both directions: a correction of 1.5
 * pieces was typed, shown as "+1.5" and saved — half a piece into the quant,
 * the ledger and the valuation — while on a line counted in kilograms the
 * −/+ buttons jumped by a whole kilogram and the browser called every
 * fraction invalid, a verdict nothing on screen read.
 *
 * The buttons and the field take the touch height below `md:` and the
 * desktop density above it, like every icon button and field: compact
 * 28px buttons were what the phone's list of goods with no order offered a
 * thumb, beside the receiving session's own 44px stepper. They keep their
 * width in a row the field stretches across, where a flex row squeezed
 * them to 37px.
 */
export function LineQuantityStepper({
  value,
  onChange,
  min,
  max,
  uomId,
  label,
  className,
}: Props) {
  const { t } = useTranslation(["common"]);
  const precision = useUomPrecision(uomId);
  const clamp = (next: number) =>
    Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next));
  // The buttons move by the same step the field accepts, so a click can
  // never land on a value the unit refuses. With no unit named, or none
  // read yet, there is no step to move by — the fallback is permissive
  // ("any"), which is not a number a button can add — so a click moves by
  // one, as it always did.
  const buttonStep = precision.stepString === "any" ? 1 : precision.step;
  const byStep = (direction: 1 | -1) => {
    const next = value + direction * buttonStep;
    const onStep = Math.round(next / buttonStep) * buttonStep;
    return clamp(Number(onStep.toFixed(precision.decimalPlaces)));
  };

  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="shrink-0"
        onClick={() => onChange(byStep(-1))}
        disabled={min !== undefined && value <= min}
        aria-label={t("common:actions.decrease")}
      >
        <Minus size={16} />
      </Button>
      <QuantityInput
        uomId={uomId}
        min={min}
        max={max}
        value={value}
        onQuantityChange={onChange}
        aria-label={label}
        className={`w-24 text-center ${className ?? ""}`}
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="shrink-0"
        onClick={() => onChange(byStep(1))}
        disabled={max !== undefined && value >= max}
        aria-label={t("common:actions.increase")}
      >
        <Plus size={16} />
      </Button>
    </div>
  );
}
