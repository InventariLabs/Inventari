import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

/** A location's average over its limited shelves — one plain segment. */
export function AverageFill({
  average,
  size = "regular",
}: {
  average: number;
  size?: "regular" | "compact";
}) {
  const { t } = useTranslation("warehouse");
  return (
    <span
      className="flex items-center gap-2"
      title={t("occupancy.average", { fill: average })}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex overflow-hidden rounded bg-surface-raised",
          size === "compact" ? "h-1.5 w-10" : "h-2 w-32",
        )}
      >
        <span
          className="h-full bg-blue-400"
          style={{ width: `${Math.min(average, 100)}%` }}
        />
      </span>
      <span className="text-xs tabular-nums text-on-secondary">
        {size === "compact"
          ? t("occupancy.percent", { fill: average })
          : t("occupancy.average", { fill: average })}
      </span>
    </span>
  );
}
