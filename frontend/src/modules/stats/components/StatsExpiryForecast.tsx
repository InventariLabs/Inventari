import { Calendar } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";
import type { ExpiryForecast } from "@/types";
import { TranslateFn } from "@/types/i18n";

const PERIOD_TRANSLATIONS_KEYS: Record<string, string> = {
  Expired: "dashboard.expired",
  Today: "dashboard.today",
  Tomorrow: "dashboard.tomorrow",
  "This week": "dashboard.thisWeek",
  "Next 2 weeks": "dashboard.next2Weeks",
  "This month": "dashboard.thisMonth",
};

type Props = {
  t: TranslateFn;
  expiryForecast: ExpiryForecast[];
};

export function StatsExpiryForecast({ t, expiryForecast }: Props) {
  return (
    <Card className="p-4 sm:p-8 border border-transparent">
      <h2 className="text-sm font-semibold text-on-muted uppercase tracking-wide mb-4 sm:mb-8 ml-1 flex items-center gap-2">
        <Calendar size={16} />
        {t("stats:expiryForecast")}
      </h2>
      {expiryForecast && expiryForecast.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-4">
          {expiryForecast.map((forecast) => (
            <div
              key={forecast.period}
              className={cn(
                "p-2.5 sm:p-5 rounded-2xl text-center transition-all border",
                forecast.period === "Expired"
                  ? "bg-red-50 border-red-200 text-on-danger dark:bg-red-500/10 dark:border-red-500/20"
                  : forecast.period === "Today" ||
                      forecast.period === "Tomorrow"
                    ? "bg-amber-50 border-amber-200 text-on-warning dark:bg-amber-500/10 dark:border-amber-500/20"
                    : "bg-surface border-border text-on-secondary",
              )}
            >
              <p className="text-lg sm:text-xl font-semibold mb-1">
                {forecast.count}
              </p>
              {/* No opacity dial on the label: at 10px the tinted tiles'
                  colour half only clears AA at full strength (a 70% wash of
                  `on-warning` on amber-50 measured ~4.3:1). */}
              <p className="text-[10px] font-medium uppercase tracking-tight leading-tight break-words">
                {PERIOD_TRANSLATIONS_KEYS[forecast.period]
                  ? t(PERIOD_TRANSLATIONS_KEYS[forecast.period], {
                      ns: "common",
                    })
                  : forecast.period}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-on-muted text-center py-12 font-medium italic">
          {t("stats:noExpiryData")}
        </p>
      )}
    </Card>
  );
}
