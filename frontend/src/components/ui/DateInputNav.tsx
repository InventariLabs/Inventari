import { useTranslation } from "react-i18next";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { Button } from "@/components/ui/Button";

interface DateInputNavProps {
  monthLabel: string;
  /** Step the focused month by ±1. */
  onStep: (months: number) => void;
  /** Step the focused year by ±1. */
  onStepYear: (years: number) => void;
}

/**
 * Month and year navigation for the `DateInput` panel.
 *
 * The year arrows are not decoration: with month steps alone, a date three
 * years out costs 36 clicks on the chevron, which is what the shortcut bar
 * above the calendar kept being asked to paper over. A year arrow steps one
 * year a click, so a date three years out is three clicks, not 36.
 */
export function DateInputNav({
  monthLabel,
  onStep,
  onStepYear,
}: DateInputNavProps) {
  const { t } = useTranslation(["common"]);

  return (
    <div className="flex items-center justify-between gap-1">
      <div className="flex items-center">
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onStepYear(-1)}
          aria-label={t("common:datePicker.previousYear")}
        >
          <ChevronsLeft size={16} />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onStep(-1)}
          aria-label={t("common:datePicker.previousMonth")}
        >
          <ChevronLeft size={16} />
        </Button>
      </div>
      <span className="text-sm font-semibold text-on" aria-live="polite">
        {monthLabel}
      </span>
      <div className="flex items-center">
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onStep(1)}
          aria-label={t("common:datePicker.nextMonth")}
        >
          <ChevronRight size={16} />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onStepYear(1)}
          aria-label={t("common:datePicker.nextYear")}
        >
          <ChevronsRight size={16} />
        </Button>
      </div>
    </div>
  );
}
