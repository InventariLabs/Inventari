import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { DateInput } from "@/components/ui/DateInput";
import { NativeSelect } from "@/components/ui/NativeSelect";

interface ProductionListFiltersProps {
  sort: string;
  dateFrom: string;
  dateTo: string;
  /** Whether anything here differs from the default — drives the reset row. */
  hasActiveFilters: boolean;
  onSortChange: (value: string) => void;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onReset: () => void;
}

/**
 * The expandable filter drawer of the production runs list: ordering and a
 * date range, plus a way back to the defaults once any of them is set.
 */
export function ProductionListFilters({
  sort,
  dateFrom,
  dateTo,
  hasActiveFilters,
  onSortChange,
  onDateFromChange,
  onDateToChange,
  onReset,
}: ProductionListFiltersProps) {
  const { t } = useTranslation("maker");

  return (
    <div
      data-testid="maker-list-filters"
      className="grid grid-cols-1 items-end sm:grid-cols-3 gap-2 sm:gap-3 p-3 sm:p-4 bg-surface-card rounded-xl border border-border animate-in slide-in-from-top-2 duration-200"
    >
      <div>
        <NativeSelect
          label={t("productionList.sortLabel")}
          value={sort}
          onChange={(e) => onSortChange(e.target.value)}
          data-testid="maker-list-sort"
        >
          <option value="newest">{t("productionList.sort.newest")}</option>
          <option value="oldest">{t("productionList.sort.oldest")}</option>
          <option value="cost_desc">{t("productionList.sort.costDesc")}</option>
        </NativeSelect>
      </div>
      <div>
        <DateInput
          label={t("productionList.dateFrom")}
          value={dateFrom}
          onChange={onDateFromChange}
          presets={["today", "minus1Week", "minus1Month"]}
        />
      </div>
      <div>
        <DateInput
          label={t("productionList.dateTo")}
          value={dateTo}
          min={dateFrom || undefined}
          onChange={onDateToChange}
          presets={["today", "plus1Week", "plus1Month"]}
        />
      </div>
      {hasActiveFilters && (
        <div className="sm:col-span-3 flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<X size={14} />}
            onClick={onReset}
          >
            {t("productionList.resetFilters", {
              defaultValue: "Reset filters",
            })}
          </Button>
        </div>
      )}
    </div>
  );
}
