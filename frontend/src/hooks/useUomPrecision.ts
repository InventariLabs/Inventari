import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";

export interface UomPrecision {
  /** HTML input step string, e.g. "1", "0.01", "0.001" */
  stepString: string;
  /** Numeric step value */
  step: number;
  /** Minimum allowed value */
  min: number;
  /** True when the UoM requires integer quantities (rounding >= 1) */
  isInteger: boolean;
  /** Number of significant decimal places allowed */
  decimalPlaces: number;
}

/**
 * The quantity columns' scale (`numeric(12,3)`): a step finer than this is
 * rounded away by the database anyway, so the screen floors a unit's step at
 * this value before it counts places. The server does not: it counts places
 * from the unit's raw `rounding`. The two agree for every seeded unit
 * (0.001, 0.01, 1.0) and differ only for a unit finer than 0.001, which the
 * product cannot create today.
 *
 * The same mirror as `QUANTITY_MAX` in `modules/shopping_lists/quantityBounds.ts`,
 * and `npm run check:quantity-bounds` compares both against
 * `app/schemas/validators.py`: the backend's `QUANTITY_SCALE` derives this
 * step, and a change there must reach this line before the gate is green.
 */
export const QUANTITY_STEP = 0.001;

const FALLBACK: UomPrecision = {
  stepString: "any",
  step: QUANTITY_STEP,
  min: QUANTITY_STEP,
  isInteger: false,
  decimalPlaces: 3,
};

/**
 * Decimal places the step really keeps — 2 for a centimetre, whatever the
 * wire's text scale says. The API serializes `rounding` as the column's
 * text (`'0.010000'`, `numeric(12,6)`), so counting the string's decimals
 * answered 6 for every measured unit while the server refuses at the
 * step's own places — the same count as the backend's
 * `_kept_decimal_places` over the normalized step.
 */
function keptDecimalPlaces(step: number): number {
  const normalized = String(step);
  if (normalized.includes("e") || normalized.includes("E")) {
    const [, exp] = normalized.toLowerCase().split("e");
    return Math.abs(Number(exp));
  }
  const dot = normalized.indexOf(".");
  return dot === -1 ? 0 : normalized.length - dot - 1;
}

/** The constraints a unit names, or the permissive fallback when none does. */
function precisionOf(rounding: unknown): UomPrecision {
  // The wire sends rounding as text ('0.010000'); the step is the number
  // it names, floored at the quantity columns' scale (the server does not
  // floor; see QUANTITY_STEP).
  const stepValue = Math.max(Number(rounding), QUANTITY_STEP);
  if (!Number.isFinite(stepValue)) return FALLBACK;

  if (stepValue >= 1) {
    return {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };
  }

  // e.g. 0.010000 → step 0.01, "0.01", 2 decimal places
  // e.g. 0.001000 → step 0.001, "0.001", 3 decimal places
  return {
    stepString: String(stepValue),
    step: stepValue,
    min: stepValue,
    isInteger: false,
    decimalPlaces: keptDecimalPlaces(stepValue),
  };
}

/**
 * Resolves quantity input constraints from a UoM id using the cached flat UoM list.
 * Falls back to permissive defaults when the id is null/undefined or not yet loaded.
 */
export function useUomPrecision(
  uomId: string | null | undefined,
): UomPrecision {
  const { data: uoms } = useFlatUoms();

  return useMemo<UomPrecision>(() => {
    if (!uomId || !uoms) return FALLBACK;
    const uom = uoms.find((u) => u.id === uomId);
    return uom ? precisionOf(uom.rounding) : FALLBACK;
  }, [uomId, uoms]);
}

/**
 * The same constraints, for a screen that only knows the unit's symbol.
 *
 * The picking and receiving lines carry `uom_symbol` and no id — the whole
 * WMS surface speaks in symbols, down to the label beside the number. A
 * symbol is not a key, so this takes the first unit that answers to it;
 * where two units of one organization share a symbol they also share a
 * step, because a symbol is what a reader counts in.
 */
export function useUomPrecisionBySymbol(
  symbol: string | null | undefined,
): UomPrecision {
  const { data: uoms } = useFlatUoms();

  return useMemo<UomPrecision>(() => {
    if (!symbol || !uoms) return FALLBACK;
    const uom = uoms.find((u) => u.symbol === symbol);
    return uom ? precisionOf(uom.rounding) : FALLBACK;
  }, [symbol, uoms]);
}

/** Why this value does not fit the unit, or "" when it does. */
export function quantityStepMessage(
  raw: number | string,
  precision: UomPrecision,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const value = typeof raw === "number" ? raw : parseFloat(raw);
  if (!Number.isFinite(value)) return "";

  if (value < precision.min) {
    return t("units.validation.belowMin", { min: precision.min });
  }
  if (precision.isInteger) {
    return value === Math.trunc(value)
      ? ""
      : t("units.validation.integerRequired");
  }
  if (precision.decimalPlaces <= 0) return "";

  const factor = Math.pow(10, precision.decimalPlaces);
  const rounded = Math.round(value * factor) / factor;
  if (Math.abs(value - rounded) > 1e-9) {
    return t("units.validation.tooManyDecimals", {
      places: precision.decimalPlaces,
    });
  }
  if (
    Math.abs(value / precision.step - Math.round(value / precision.step)) > 1e-9
  ) {
    return t("units.validation.notOnStep", { step: precision.step });
  }
  return "";
}

/**
 * Ask any quantity whether its unit can hold it — one line at a time.
 *
 * A form with a line per row cannot call a hook per row, and it still has
 * to know whether to let the save through: a correction whose delta the
 * unit cannot hold reached the ledger as 1.5 of something counted in
 * pieces. This returns a plain function over the same cached catalogue, so
 * a screen can ask about ten lines in one render and disable its button on
 * the answer.
 *
 * Empty string means "the unit can hold this" — including while the field
 * is empty or half-typed, which is not an error the reader needs shouting
 * about yet.
 */
export function useQuantityStepCheck(): (
  value: number | string,
  unit: { uomId?: string | null; uomSymbol?: string | null },
) => string {
  const { data: uoms } = useFlatUoms();
  const { t } = useTranslation("common");

  return useCallback(
    (value, unit) => {
      const uom = uoms?.find((u) =>
        unit.uomId ? u.id === unit.uomId : u.symbol === unit.uomSymbol,
      );
      if (!uom) return "";
      return quantityStepMessage(value, precisionOf(uom.rounding), t);
    },
    [uoms, t],
  );
}
