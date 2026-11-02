import { useTranslation } from "react-i18next";
import { Check, MapPin } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { TranslateFn } from "@/types/i18n";

/** One place the reader may count, with what is known about its counting. */
export interface CountablePlace {
  id: string;
  path: string;
  lastCountedAt: string | null;
  /** The count open on this place now, when one is. */
  stockTakeId: string | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** "Last counted 12 days ago", "Counted today", or "Never counted". */
function lastCountedText(
  t: TranslateFn,
  lastCountedAt: string | null,
  now: Date = new Date(),
): string {
  if (!lastCountedAt) return t("stock_takes:count.neverCounted");
  const days = Math.floor(
    (now.getTime() - new Date(lastCountedAt).getTime()) / DAY_MS,
  );
  if (days <= 0) return t("stock_takes:count.countedToday");
  return t("stock_takes:count.lastCounted", { count: days });
}

/**
 * The places to count, the longest without a count first. A place under an
 * open count says so and opens that count instead of being chosen again: one
 * count per place at a time.
 */
export function CountLocationList({
  places,
  selectedId,
  onSelect,
  onResume,
}: {
  places: CountablePlace[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onResume: (stockTakeId: string) => void;
}) {
  const { t } = useTranslation("stock_takes");
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-surface-card">
      {places.map((place) => {
        const selected = place.id === selectedId;
        return (
          <li key={place.id}>
            <Button
              variant="ghost"
              size="content"
              aria-pressed={place.stockTakeId ? undefined : selected}
              onClick={() =>
                place.stockTakeId
                  ? onResume(place.stockTakeId)
                  : onSelect(place.id)
              }
              className={`w-full justify-start gap-3 rounded-none px-4 py-3 text-left ${selected ? "bg-surface-raised" : ""}`}
            >
              <MapPin size={18} className="shrink-0 text-on-muted" />
              <span className="flex min-w-0 flex-1 flex-col items-start">
                <span className="font-medium text-on break-words">
                  {place.path}
                </span>
                <span className="text-sm text-on-secondary">
                  {lastCountedText(t, place.lastCountedAt)}
                </span>
              </span>
              {place.stockTakeId ? (
                <Badge variant="outline">{t("count.underWay")}</Badge>
              ) : (
                selected && (
                  <Check size={18} className="shrink-0 text-on-success" />
                )
              )}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
