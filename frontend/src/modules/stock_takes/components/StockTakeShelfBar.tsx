import { useTranslation } from "react-i18next";
import { CheckCircle, MapPin, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { ClosedLocation } from "@/modules/stock_takes/types/stock-takes";
import type { useShelfCounting } from "@/modules/stock_takes/hooks/useShelfCounting";

interface Props {
  counting: ReturnType<typeof useShelfCounting>;
  /** The shelves closed so far; the current one's closure is read from it. */
  closedLocations: ClosedLocation[];
}

/**
 * Which shelf the count stands at. A scanned location label sets it; until
 * then the bar says that a shelf label can be scanned, so counting by
 * location is something the reader can find without being told.
 *
 * Standing at a shelf, the counter closes it when done: what nobody counted
 * there becomes 0, and an empty shelf is confirmed as counted. A closed shelf
 * says so, and by whom.
 */
export default function StockTakeShelfBar({
  counting,
  closedLocations,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  const { shelf } = counting;
  if (!shelf) {
    return (
      <p className="flex items-center gap-2 text-sm text-on-muted">
        <ScanLine size={16} className="shrink-0" />
        {t("shelf.hint")}
      </p>
    );
  }
  const closed = closedLocations.find(
    (closure) => closure.location_id === shelf.id,
  );
  return (
    <div
      role="status"
      data-testid="stock-take-shelf"
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary-500/40 bg-primary-50 px-3 py-2 dark:bg-primary-500/10"
    >
      <div className="min-w-0 space-y-0.5">
        <p className="flex min-w-0 items-center gap-2 text-sm text-on-secondary">
          <MapPin size={16} className="shrink-0 text-primary-600" />
          <span className="min-w-0 break-words">
            {t("shelf.counting")}{" "}
            <span className="font-medium text-on-primary">{shelf.path}</span>
          </span>
        </p>
        {closed && (
          <p className="flex items-center gap-2 text-xs text-on-secondary">
            <CheckCircle size={14} className="shrink-0 text-success-600" />
            {closed.empty
              ? t("shelf.closedEmptyBy", { name: closed.closed_by_name ?? "—" })
              : t("shelf.closedBy", { name: closed.closed_by_name ?? "—" })}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="contentSm"
          variant="primary"
          className="min-h-11 md:min-h-8 shrink-0"
          data-testid="stock-take-close-shelf"
          disabled={counting.isClosing}
          onClick={() => void counting.closeShelf()}
        >
          {t("shelf.close")}
        </Button>
        <Button
          type="button"
          size="contentSm"
          variant="outline"
          className="min-h-11 md:min-h-8 shrink-0"
          onClick={() => counting.setShelf(null)}
        >
          {t("shelf.leave")}
        </Button>
      </div>
    </div>
  );
}
