import type { ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { makeTDynamic } from "@/lib/i18nHelpers";
import type { FieldDefinition } from "@/types";
import { Input } from "@/components/ui/Input";
import { normalizeMoneyValue } from "./MoneyField";
import { getLabel } from "./helpers";

interface MoneyFieldProps {
  /** Id the surrounding label points at — lands on the amount input. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  commonClasses: string;
  error?: string;
  onChange: (val: { amount: string; currency: string }) => void;
}

/**
 * Renders a `money` field: an amount input + a currency chip.
 *
 * The component is controlled — every keystroke emits a fresh
 * ``{amount, currency}`` object so the parent can persist it as
 * ``meta_data[key]`` without re-shaping.
 */
export function MoneyField({
  id,
  field,
  value,
  commonClasses,
  error,
  onChange,
}: MoneyFieldProps) {
  // `items` joins `common` because the field's label is resolved through
  // the same `getLabel` the other renderers use.
  const { t } = useTranslation(["items", "common"]);
  const tDyn = makeTDynamic(t);
  const { amount, currency } = normalizeMoneyValue(
    value,
    field.default_currency,
  );

  const handleAmountChange = (e: ChangeEvent<HTMLInputElement>) => {
    const next = e.target.value;
    onChange({ amount: next, currency });
  };

  return (
    <div className="flex items-stretch gap-2">
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        step="any"
        value={amount}
        onChange={handleAmountChange}
        // Named from the same source as the visible label the parent renders.
        aria-label={getLabel(field, tDyn)}
        placeholder="0.00"
        className={`flex-1 ${commonClasses} ${error ? "border-red-300 bg-red-50" : ""}`}
      />
      <span
        // Explicit namespace: this file binds both `items` and `common`, and
        // the key lives in `common`.
        aria-label={t("common:a11y.currency")}
        className="inline-flex items-center px-3 rounded-lg border border-border bg-surface text-sm font-semibold text-on-secondary"
      >
        {currency}
      </span>
    </div>
  );
}
