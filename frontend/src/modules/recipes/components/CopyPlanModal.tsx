import { format } from "date-fns";
import type { TFunction } from "i18next";
import { Button } from "@/components/ui/Button";

import { DateInput } from "@/components/ui/DateInput";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetTitle,
} from "@/components/ui/Sheet";

interface CopyPlanModalProps {
  copyStart: string;
  copyEnd: string;
  isPending: boolean;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
  onConfirm: () => void;
  onClose: () => void;
  t: TFunction;
}

/**
 * CopyPlanModal — bottom sheet (mobile) / centered dialog (desktop) asking for
 * the target date range when copying a meal plan to another week.
 */
export function CopyPlanModal({
  copyStart,
  copyEnd,
  isPending,
  onStartChange,
  onEndChange,
  onConfirm,
  onClose,
  t,
}: CopyPlanModalProps) {
  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="confirm"
      maxWidth="md"
      aria-label={t("recipes:meal_planner.copy_to_title")}
    >
      <SheetBody className="p-5">
        <SheetTitle className="text-sm mb-4">
          {t("recipes:meal_planner.copy_to_title")}
        </SheetTitle>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-on-secondary">
              {t("recipes:meal_planner.copy_start_date")}
            </span>
            <DateInput
              value={copyStart}
              onChange={(e) => onStartChange(e)}
              min={format(new Date(), "yyyy-MM-dd")}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-on-secondary">
              {t("recipes:meal_planner.copy_end_date")}
            </span>
            <DateInput
              value={copyEnd}
              onChange={(e) => onEndChange(e)}
              min={copyStart || undefined}
            />
          </label>
        </div>
        <SheetActions className="mt-5">
          <Button variant="outline" onClick={onClose}>
            {t("common:form.cancel")}
          </Button>
          <Button onClick={onConfirm} disabled={isPending}>
            {t("recipes:meal_planner.copy_confirm")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
