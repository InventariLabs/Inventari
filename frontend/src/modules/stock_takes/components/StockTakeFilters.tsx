import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";

interface Props {
  showDiscrepancies: boolean;
  onShowAll: () => void;
  onShowDiscrepancies: () => void;
  totalCount: number;
  discrepanciesCount: number;
  surplusCount: number;
  locationLevels: string[];
  locationLevelFilter: string;
  onLocationLevelFilterChange: (level: string) => void;
}

export default function StockTakeFilters({
  showDiscrepancies,
  onShowAll,
  onShowDiscrepancies,
  totalCount,
  discrepanciesCount,
  surplusCount,
  locationLevels,
  locationLevelFilter,
  onLocationLevelFilterChange,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  return (
    <div className="flex gap-2 flex-wrap items-center">
      <Button
        type="button"
        onClick={onShowAll}
        variant="outline"
        size="contentSm"
        className={`min-h-11 md:min-h-8 px-4 py-2 font-medium text-sm ${
          !showDiscrepancies
            ? "bg-primary-50 hover:bg-primary-50 text-primary-700 dark:text-primary-500 dark:bg-primary-500/10 dark:hover:bg-primary-500/10 border border-primary-500/40"
            : "bg-surface-card hover:bg-surface-card text-on-secondary border border-border"
        }`}
      >
        {t("filters.all")} ({totalCount})
      </Button>
      <Button
        type="button"
        onClick={onShowDiscrepancies}
        variant="outline"
        size="contentSm"
        className={`flex min-h-11 md:min-h-8 items-center gap-2 px-4 py-2 font-medium text-sm ${
          showDiscrepancies
            ? "bg-amber-50 hover:bg-amber-50 text-on-warning dark:bg-amber-500/10 dark:hover:bg-amber-500/10 border border-amber-500/40"
            : "bg-surface-card hover:bg-surface-card text-on-secondary border border-border"
        }`}
      >
        <AlertTriangle size={16} />
        {t("filters.discrepancies")} ({discrepanciesCount})
      </Button>

      {surplusCount > 0 && (
        <span className="text-xs font-medium text-on-secondary bg-surface-card border border-border rounded-lg px-3 py-2">
          {t("surplusCount", { count: surplusCount })}
        </span>
      )}

      {locationLevels.length > 0 && (
        <NativeSelect
          wrapperClassName="w-fit"
          value={locationLevelFilter}
          onChange={(e) => onLocationLevelFilterChange(e.target.value)}
          aria-label={t("filters.locationLevel")}
          className="h-auto min-h-11 md:min-h-8 py-2 text-sm"
        >
          <option value="">{t("filters.allLevels")}</option>
          {locationLevels.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </NativeSelect>
      )}
    </div>
  );
}
