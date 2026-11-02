import { formatNumberLocale, toAmount } from "@/utils/formatters";

interface NutritionBadgeProps {
  // The wire carries a nutrition figure as a Decimal string, absent when
  // the source had none; a computed figure arrives a number.
  value: number | string | null | undefined;
  unit: string;
}

export function NutritionBadge({ value, unit }: NutritionBadgeProps) {
  const n = toAmount(value);
  if (n == null) return <span className="text-on-muted">—</span>;
  return (
    <span className="text-xs text-on-secondary">
      {formatNumberLocale(n, 1)}
      <span className="text-on-muted ml-0.5">{unit}</span>
    </span>
  );
}
