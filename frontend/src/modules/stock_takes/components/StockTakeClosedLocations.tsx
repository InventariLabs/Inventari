import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { formatDateTime } from "@/utils/formatters";
import type { ClosedLocation } from "@/modules/stock_takes/types/stock-takes";

interface Props {
  closedLocations: ClosedLocation[];
}

/**
 * Which locations the counters closed, and who: an empty location leaves no
 * line behind, so this list is its only trace in the report.
 */
export default function StockTakeClosedLocations({ closedLocations }: Props) {
  const { t } = useTranslation(["stock_takes"]);
  if (closedLocations.length === 0) return null;
  return (
    <Card className="p-4 space-y-2">
      <h2 className="text-sm font-semibold text-on">
        {t("report.closedLocations")}
      </h2>
      <ul className="divide-y divide-border">
        {closedLocations.map((closed) => (
          <li
            key={closed.location_id ?? closed.path}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2 text-sm"
          >
            <span className="min-w-0 break-words font-medium text-on">
              {closed.path}
            </span>
            <span className="flex flex-wrap items-center gap-2 text-xs text-on-secondary">
              <Badge
                variant={closed.empty ? "outline" : "info"}
                className="text-[10px]"
              >
                {closed.empty
                  ? t("report.closedEmpty")
                  : t("report.closedCounted")}
              </Badge>
              {t("report.closedByAt", {
                name: closed.closed_by_name ?? "—",
                at: formatDateTime(closed.closed_at),
              })}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
