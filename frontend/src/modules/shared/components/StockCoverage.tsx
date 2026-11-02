import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

export type StockCoverageTone = "ok" | "partial" | "none";

interface StockCoverageProps {
  /** Required lines with enough on the shelf. */
  available: number;
  /** Required lines in total; optional ones count towards neither. */
  total: number;
  /** Required lines whose measure could not be put on one scale with the
   *  shelf's — neither "have" nor "missing", so they are named instead. */
  incomparable?: number;
  /** Pass the tone when the caller already computed it, to avoid two answers. */
  tone?: StockCoverageTone;
  /** Icon size; 12 sits inside a Badge, 14 beside body text. */
  iconSize?: number;
}

const ICONS = {
  ok: CheckCircle2,
  partial: AlertTriangle,
  none: AlertTriangle,
} as const;

export function toneForCoverage(
  available: number,
  total: number,
): StockCoverageTone {
  if (total > 0 && available === total) return "ok";
  return available > 0 ? "partial" : "none";
}

/**
 * How much of a recipe is on the shelf, written the one way.
 *
 * The same computed number used to reach the reader in three notations: the
 * recipe card wrote "5/5" and explained it in a `title` nobody on a phone can
 * open; the same card on the "I can cook" tab wrote "100%"; the planner's
 * suggestions wrote a percent icon followed by a bare "100", which a screen
 * reader announced as the number alone. The percentage was always a rounding
 * of the ratio — 80% of five ingredients cannot be turned back into "4 of 5",
 * and it is the missing one the reader is after.
 *
 * Inline content only, no chrome: the card wraps this in a Badge, the maker
 * screens in a line of muted text with the batch count after it. One notation
 * does not require one widget, and forcing the pill onto a detail line would
 * have cost more than it settled.
 */
export function StockCoverage({
  available,
  total,
  incomparable = 0,
  tone,
  iconSize = 12,
}: StockCoverageProps) {
  const { t } = useTranslation("common");
  const resolved = tone ?? toneForCoverage(available, total);
  const Icon = ICONS[resolved];

  return (
    <>
      <Icon size={iconSize} aria-hidden className="shrink-0" />
      <span aria-hidden>
        {available}/{total} {t("stockCoverage.label")}
      </span>
      {incomparable > 0 && (
        <span aria-hidden className="ml-1">
          {t("stockCoverage.incomparable", { count: incomparable, total })}
        </span>
      )}
      {/* "5 slash 5 in stock" is what a screen reader makes of the ratio, so
          the sentence is spelled out for it rather than left in a title. */}
      <span className="sr-only">
        {t("stockCoverage.summary", { available, total })}
        {incomparable > 0
          ? ` ${t("stockCoverage.incomparable", { count: incomparable, total })}`
          : ""}
      </span>
    </>
  );
}
