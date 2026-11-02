import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, type InputProps } from "@/components/ui/Input";
import {
  quantityStepMessage,
  useUomPrecision,
  useUomPrecisionBySymbol,
} from "@/hooks/useUomPrecision";

export interface QuantityInputProps extends Omit<
  InputProps,
  "type" | "step" | "min"
> {
  /**
   * UoM id used to resolve step/precision constraints.
   * Falls back to permissive defaults (step="any") when null or undefined.
   */
  uomId?: string | null;
  /**
   * The unit's symbol, for a screen that has no id to hand. The WMS lines
   * carry `uom_symbol` and nothing else — the whole surface speaks in
   * symbols, down to the label beside the number. Ignored when `uomId` is
   * given.
   */
  uomSymbol?: string | null;
  /**
   * Floor this particular field allows, when its own domain reaches lower
   * than the unit's. The execution screen is the case: a line nobody has
   * received yet sits at zero, and zero is what "Clear" means there, while
   * the unit refuses a quantity that small anywhere one is *entered*; a
   * correction delta's lower bound is what the line executed and may sit
   * below zero. Defaults to the unit's own minimum, and the unit still
   * decides the step and the decimals.
   */
  min?: number;
  value: number | string;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  /**
   * The committed-value alternative to `onChange`, for callers whose state
   * is a number. It receives the number the text holds — or `null` while
   * the text holds none yet, which is every incomplete step of a fraction
   * being typed: a number input reports the half-typed "12." as an empty
   * string, and the caller that answered `onChange` with
   * `Number("") === 0` rewrote the field to "0" mid-typing, destroying the
   * dot the reader was still holding. While this prop is given
   * the field keeps the typed text itself and shows `value` again on blur,
   * so `onChange` is not called. The two props are mutually exclusive.
   */
  onQuantityChange?: (quantity: number | null) => void;
}

/**
 * Number input that enforces UoM quantity precision rules.
 *
 * - Sets `step` and `min` attributes based on `uom.rounding`.
 * - Shows an inline validation error for fractional values when the UoM
 *   requires whole numbers (rounding >= 1).
 * - Falls back to `step="any"` when the unit is absent or not yet loaded.
 *
 * The value it is *given* is checked too, not only the one somebody types:
 * a field showing a number its own `min` forbids has to say so, and `Input`
 * turns an error into `aria-invalid` plus a message a screen reader reaches.
 */
export function QuantityInput({
  uomId,
  uomSymbol,
  min,
  value,
  onChange,
  onQuantityChange,
  onBlur,
  error,
  ...props
}: QuantityInputProps) {
  const { t } = useTranslation("common");
  const byId = useUomPrecision(uomId);
  const bySymbol = useUomPrecisionBySymbol(uomSymbol);
  const unitPrecision = uomId ? byId : bySymbol;
  // The caller's floor wins where it is given, and the step and the
  // decimals stay the unit's.
  const precision = useMemo(
    () => (min === undefined ? unitPrecision : { ...unitPrecision, min }),
    [unitPrecision, min],
  );
  const [typedError, setTypedError] = useState<string>("");
  // The text of a field in committed-value mode, from the first change
  // until blur. Echoing the browser's report verbatim — including the empty
  // one of a half-typed fraction — is what lets React leave the input's
  // editing buffer alone; rewriting it to a number is what used to eat the
  // dot. `null` means nobody is typing: the field shows `value`.
  const [draft, setDraft] = useState<string | null>(null);
  const ownsTyping = onQuantityChange !== undefined;
  const displayed = ownsTyping ? (draft ?? value) : value;

  const valueError = useMemo(
    () => quantityStepMessage(displayed, precision, t),
    [displayed, precision, t],
  );

  // A parent may clamp what was typed — a line you can still receive two of
  // takes 2, not the 2.5 somebody tried — and the sentence about the typed
  // text must not outlive the value it described: "2" under "whole numbers
  // only" is the field contradicting itself. In committed-value mode the
  // sentence is computed from the displayed text each render and needs no
  // state; this effect belongs to the `onChange` mode only.
  useEffect(() => {
    if (ownsTyping) return;
    setTypedError((current) =>
      current && !quantityStepMessage(value, precision, t) ? "" : current,
    );
  }, [ownsTyping, value, precision, t]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (ownsTyping) {
      setDraft(event.target.value);
      onQuantityChange?.(parseDraftedQuantity(event.target.value));
      return;
    }
    setTypedError(quantityStepMessage(event.target.value, precision, t));
    onChange?.(event);
  };

  const handleBlur = (event: React.FocusEvent<HTMLInputElement>) => {
    if (ownsTyping) setDraft(null);
    onBlur?.(event);
  };

  return (
    <Input
      type="number"
      step={precision.stepString}
      min={precision.min}
      value={displayed}
      onChange={handleChange}
      onBlur={handleBlur}
      error={typedError || valueError || error}
      {...props}
    />
  );
}

/**
 * The number a quantity text holds, or null while it holds none. The empty
 * report of a half-typed fraction and an emptied field are both null — a
 * zero the reader actually typed is a number the caller must hear about.
 */
function parseDraftedQuantity(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}
