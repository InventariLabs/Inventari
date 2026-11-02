import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { statusTone, type OccupancyCell } from "./occupancyModel";

interface FillBarProps {
  cell: OccupancyCell;
  /** `compact` is the bar of a dense tree row; `regular` the occupancy screen's. */
  size?: "regular" | "compact";
  className?: string;
}

/**
 * One location's fill: a bar made of one segment per limited product, whose
 * widths are the products' shares and whose total is the fill, with the number
 * beside it — the colour is never the only carrier of the state.
 *
 * A location nobody limited has no fill, and none is drawn: a dashed outline
 * and its quantity, or "empty". Inventing a bar from a count of records would
 * be a lie with a colour on it.
 */
export function FillBar({ cell, size = "regular", className }: FillBarProps) {
  const { t } = useTranslation("warehouse");
  const compact = size === "compact";

  if (cell.fill === null) {
    return (
      <span
        className={cn(
          "flex items-center gap-2 text-xs text-on-secondary",
          className,
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "rounded border border-dashed border-border",
            compact ? "h-1.5 w-10" : "h-2 w-32",
          )}
        />
        {cell.status === "empty"
          ? t("occupancy.empty")
          : t("occupancy.noLimit")}
      </span>
    );
  }

  const tone = statusTone(cell.status);
  // A limited location with nothing on it says "Empty", not "0%": the track
  // is drawn because a limit exists, the word because that is what a person
  // looking for a free place wants to read.
  const emptyLabel = cell.status === "empty" ? t("occupancy.empty") : null;
  const segments = cell.entries.filter(
    (entry) => entry.share !== null && entry.share > 0,
  );
  // Past 100% the bar is full and the segments keep their proportions.
  const scale = cell.fill > 100 ? 100 / cell.fill : 1;

  return (
    <span className={cn("flex items-center gap-2", className)}>
      <span
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(cell.fill, 100)}
        aria-valuetext={t("occupancy.percent", { fill: cell.fill })}
        aria-label={cell.location_name ?? undefined}
        className={cn(
          "flex overflow-hidden rounded bg-surface-raised",
          compact ? "h-1.5 w-10" : "h-2 w-32",
        )}
      >
        {segments.map((entry) => (
          <span
            key={entry.product_template_id}
            title={`${entry.product_template_name ?? ""}: ${entry.share}%`}
            className={cn("h-full border-r border-surface-card", tone.bar)}
            style={{ width: `${(entry.share ?? 0) * scale}%` }}
          />
        ))}
      </span>
      <span className={cn("text-xs font-medium tabular-nums", tone.text)}>
        {emptyLabel ?? t("occupancy.percent", { fill: cell.fill })}
      </span>
    </span>
  );
}
