import { formatQuantityValue } from "@/utils/formatters";

interface YieldLossNoteProps {
  /** `yield_loss_pct` of a BOM line, as the API returns it. */
  pct: number | string | null | undefined;
}

/**
 * The yield-loss annotation shown next to a BOM line quantity.
 *
 * A yield loss inflates consumption: the backend computes
 * `effective_qty = qty_per_batch * (1 + yield_loss_pct / 100)`, so 10% loss
 * means ten percent *more* material leaves stock, never less. The two views
 * of the same BOM line had drifted to opposite signs — the composition tab
 * showed `+10%`, the tree editor `(-10%)` — which is the difference between
 * "issue more" and "issue less" on the same number. One component says it
 * now, so a third view cannot invent a third sign.
 *
 * Renders nothing at zero rather than a decorated zero.
 */
export function YieldLossNote({ pct }: YieldLossNoteProps) {
  const value = Number(pct);
  if (!Number.isFinite(value) || value === 0) return null;

  return (
    <span className="text-xs text-on-muted">+{formatQuantityValue(pct)}%</span>
  );
}
