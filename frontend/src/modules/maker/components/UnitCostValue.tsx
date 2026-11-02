import { useTranslation } from "react-i18next";
import { CostFigure } from "@/modules/maker/components/CostFigure";

interface UnitCostValueProps {
  /** What the last completed run cost per unit; null when there was no run. */
  value: string | null;
  /** How many of that run's ingredients had no purchase rate. */
  uncosted: number;
  /** Overrides the "last run" wording of the unpriced note — an estimate is
   *  not a run, and its missing rates are not the last run's. */
  note?: string;
}

/**
 * What the last run cost, or a plain statement that nobody knows.
 *
 * The catalog told the same story two ways. "Unit cost —" when no run had
 * happened, and "Unit cost $0.00" when one had but none of its ingredients
 * carried a purchase price — completion prices an unknown ingredient at zero
 * so the run can finish, and the zero travelled all the way to the card as
 * though it were a measurement. The second reading is the dangerous one: it
 * says the product is free to make, and somebody sets a margin on it.
 *
 * A run that priced some ingredients and not others still shows its number,
 * because it is worth something — with a mark saying how much of the recipe
 * it left out. Only a total of zero built entirely from unknowns falls back
 * to "—": that is not a small cost, it is no answer at all.
 */
export function UnitCostValue({ value, uncosted, note }: UnitCostValueProps) {
  const { t } = useTranslation("maker");

  // One rule, one place: `CostFigure` refuses a figure that no known rate
  // contributed to. The catalog counts what the run left unpriced but not
  // what it priced, so a non-zero total is the evidence that something was —
  // an ingredient priced at a real rate cannot sum to nothing.
  const priced = value !== null && Number(value) !== 0 ? 1 : 0;

  return (
    <CostFigure
      value={value}
      priced={priced}
      unpriced={uncosted}
      note={note ?? t("catalog.unitCostIncomplete", { count: uncosted })}
    />
  );
}
