import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { useMoney } from "@/hooks/useMoney";

interface CostGapProps {
  /** Ingredients that carried a rate and are inside the figure. */
  priced: number;
  /** Ingredients that carried none and contributed zero to it. */
  unpriced: number;
}

interface CostFigureProps extends CostGapProps {
  /** The amount as the API sent it; null when nothing was computed at all. */
  value: string | number | null;
  /** A caller's own wording for the gap, when it can say more than this can. */
  note?: string;
  /**
   * Whether the figure announces the gap to assistive technology. True by
   * default — where the caller renders no note, the sr-only copy is the only
   * announcement the reader gets. Set false when this screen prints the gap
   * sentence visibly beside the figure (an amber card or a CostGapNote):
   * then the visible text is the announcement, and an sr-only repeat makes a
   * screen reader say the same sentence twice.
   */
  announce?: boolean;
  /**
   * The id of the element that prints the gap sentence visibly, when one
   * does — the caller's CostGapNote or amber card.
   *
   * This is the association a `title` used to carry, and the reason the
   * title stays gone: a title is the one channel a touch screen never
   * opens and a screen reader announces inconsistently, while an
   * aria-describedby pointing at visible text is announced as the figure's
   * own description — the figure and its explanation travel together for
   * the reader, and the sentence is neither repeated nor hover-only.
   * The reference is emitted only while something is actually missing
   * (`unpriced > 0`) — exactly when the caller's note renders. With
   * nothing missing the note is null and the figure names nothing rather
   * than describing itself with an element that is not there.
   */
  describedBy?: string;
}

/** Nothing priced and something unpriced: the sum has nothing in it. */
function isRefused({ priced, unpriced }: CostGapProps): boolean {
  return unpriced > 0 && priced === 0;
}

/**
 * A cost, or a plain statement that there was nothing to add up.
 *
 * An ingredient with no rate contributes zero, so a formula nobody has
 * priced sums to zero and the screens printed that zero as a result: an
 * ingredient row reading "—" with a Total of "$0.00" under it, a UNIT COST
 * tile of "$0.00" beside a REFERENCE PRICE of "—", a production preview
 * announcing "0.00" directly above its own warning that no rates exist. Zero
 * is the one wrong answer here, because it reads as free to make and
 * somebody sets a margin against it.
 *
 * A figure with at least one known rate keeps its number — it is worth
 * something — marked with what it leaves out. A figure built from nothing
 * but unknowns refuses: that is not a small cost, it is no answer. A zero
 * from a fully priced formula stays a number, because it is a measurement.
 */
export function CostFigure({
  value,
  priced,
  unpriced,
  note,
  announce = true,
  describedBy,
}: CostFigureProps) {
  const { t } = useTranslation("maker");
  const money = useMoney();

  if (value === null || isRefused({ priced, unpriced })) {
    return (
      <>
        {/* The dash carries the description reference too: a refused figure
            is the case the gap sentence explains hardest. The reference goes
            out only while something is actually missing — that is exactly
            when the caller's note renders. With nothing missing the note is
            null, and a describedby naming a null element is the old dangling
            title in a subtler dialect. */}
        <span aria-describedby={unpriced > 0 ? describedBy : undefined}>—</span>
        {announce && unpriced > 0 && (
          // The dash alone does not say why, and this figure sits in a tile
          // whose caption belongs to the caller — so the sentence reaches a
          // screen reader here even where the caller renders no note.
          <span className="sr-only">
            {note ?? gapSentence(t, { priced, unpriced })}
          </span>
        )}
      </>
    );
  }

  if (unpriced === 0) {
    return <>{money(value)}</>;
  }

  const sentence = note ?? gapSentence(t, { priced, unpriced });
  return (
    <span
      className="inline-flex items-baseline gap-1"
      title={announce ? sentence : undefined}
      aria-describedby={describedBy}
    >
      {money(value)}
      <AlertTriangle
        size={13}
        aria-hidden
        className="shrink-0 self-center text-amber-600 dark:text-amber-400"
      />
      {announce && <span className="sr-only">{sentence}</span>}
    </span>
  );
}

function gapSentence(
  t: (key: string, options: { count: number }) => string,
  { priced, unpriced }: CostGapProps,
): string {
  return isRefused({ priced, unpriced })
    ? t("cost.gap.none", { count: unpriced })
    : t("cost.gap.partial", { count: unpriced });
}

/**
 * The same sentence, for a caller that already has somewhere to put it.
 *
 * Returns null when every ingredient carried a rate. The production preview
 * has its own amber card for the gap; it should not say a second, different
 * thing next to the figure it explains.
 */
export function useCostGapSentence(): (gap: CostGapProps) => string | null {
  const { t } = useTranslation("maker");
  return (gap) => (gap.unpriced === 0 ? null : gapSentence(t, gap));
}

/**
 * The visible half of the same statement, for the caption line of a tile.
 *
 * Renders nothing when every ingredient carried a rate, so a caller can
 * place it unconditionally. Give the id it renders to the figures it
 * explains (`CostFigure`'s `describedBy`), so the reader gets the figure
 * and its explanation as one announcement.
 */
export function CostGapNote({
  priced,
  unpriced,
  id,
}: CostGapProps & { id?: string }) {
  const { t } = useTranslation("maker");

  if (unpriced === 0) return null;

  return (
    <p id={id} className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
      {gapSentence(t, { priced, unpriced })}
    </p>
  );
}
