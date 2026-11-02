import { extractApiError } from "@/lib/errors";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CalendarPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { format, parseISO } from "date-fns";
import { Sheet, SheetBody, SheetTitle } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { dateFnsLocale, formatDateRange, todayIso } from "@/utils/formatters";
import {
  useMealPlans,
  useAddMealPlanEntry,
} from "@/modules/recipes/hooks/useMealPlans";
import type { Recipe } from "@/modules/recipes/types/core";
import type { MealSlot } from "@/modules/recipes/types/mealplans";
import { QueryFailure } from "@/components/ui/QueryResult";

const SLOT_KEYS: Record<MealSlot, string> = {
  BREAKFAST: "breakfast",
  LUNCH: "lunch",
  DINNER: "dinner",
  SNACK: "snack",
};

function daysBetween(start: string, end: string): string[] {
  const days: string[] = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  while (cursor.getTime() <= last.getTime()) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

/**
 * header action that adds the current recipe to a meal plan.
 * Self-contained (owns its modal state), mirroring CookForStockButton.
 */
export function AddToMealPlanButton({
  recipe,
  className,
}: {
  recipe: Recipe;
  className?: string;
}) {
  const { t } = useTranslation("recipes");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        className={`gap-2 ${className ?? ""}`}
        data-testid="add-to-meal-plan-button"
      >
        <CalendarPlus size={16} />
        {t("meal_planner.add_to_plan")}
      </Button>
      <MealPlanPickerModal
        open={open}
        onClose={() => setOpen(false)}
        recipe={recipe}
      />
    </>
  );
}

interface MealPlanPickerModalProps {
  open: boolean;
  onClose: () => void;
  /** The recipe to schedule into a plan. */
  recipe: Recipe;
}

/**
 * pick plan → day → slot, then add the recipe via
 * useAddMealPlanEntry (the reverse direction of the planner's
 * RecipePickerModal). Visible for all profiles.
 */
export function MealPlanPickerModal({
  open,
  onClose,
  recipe,
}: MealPlanPickerModalProps) {
  const { t } = useTranslation("recipes");
  const navigate = useNavigate();
  const {
    data: plans = [],
    isError: plansFailed,
    error: plansError,
    refetch: refetchPlans,
  } = useMealPlans();
  const addEntry = useAddMealPlanEntry();

  const [planId, setPlanId] = useState("");
  const [date, setDate] = useState("");
  const [slot, setSlot] = useState<MealSlot | "">("");
  const [submitting, setSubmitting] = useState(false);

  const plan = plans.find((p) => p.id === planId);
  const days = useMemo(
    () => (plan ? daysBetween(plan.start_date, plan.end_date) : []),
    [plan],
  );

  /**
   * Answer what can be answered before asking.
   *
   * The modal opened on a single question — which plan — and only revealed
   * the day and the meal once it was answered, so on an installation with
   * one plan it asked the reader to choose from a list of one before it
   * would say where the recipe was going. With the plan settled, today is
   * the day if the plan covers it, and a plan running one meal has that
   * meal picked too.
   */
  useEffect(() => {
    if (!open) return;
    if (planId || plans.length !== 1) return;
    setPlanId(plans[0].id);
  }, [open, planId, plans]);

  useEffect(() => {
    if (!plan || date) return;
    // The day list is calendar days, so "today" has to be read the same
    // way — `toISOString()` answers in UTC and marked tomorrow's row for
    // anyone west of Greenwich in the evening.
    const today = todayIso();
    setDate(days.includes(today) ? today : (days[0] ?? ""));
  }, [plan, date, days]);

  useEffect(() => {
    if (!plan || slot) return;
    if (plan.enabled_slots.length === 1) setSlot(plan.enabled_slots[0]);
  }, [plan, slot]);

  const canSubmit = Boolean(planId && date && slot) && !submitting;

  const reset = () => {
    setPlanId("");
    setDate("");
    setSlot("");
  };

  const handleSubmit = async () => {
    if (!planId || !date || !slot) return;
    setSubmitting(true);
    try {
      await addEntry.mutateAsync({
        planId,
        data: { date, slot, recipe_id: recipe.id },
      });
      toast.success(t("meal_planner.added_to_plan"));
      reset();
      onClose();
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="md"
      aria-label={t("meal_planner.add_to_plan_title")}
    >
      <SheetBody className="p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-accent/10 text-accent">
            <CalendarPlus size={20} />
          </div>
          <div>
            <SheetTitle className="text-sm">
              {t("meal_planner.add_to_plan_title")}
            </SheetTitle>
            <p className="text-sm text-on-muted">{recipe.name}</p>
          </div>
        </div>

        {plansFailed ? (
          <QueryFailure error={plansError} onRetry={() => refetchPlans()} />
        ) : plans.length === 0 ? (
          <div className="space-y-4">
            <p className="text-sm text-on-muted">
              {t("meal_planner.no_plans_add_to_plan")}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                {t("common:actions.cancel")}
              </Button>
              <Button
                onClick={() => {
                  onClose();
                  navigate(`/recipes/meal-planner?new=1&recipe=${recipe.id}`);
                }}
                data-testid="meal-plan-picker-create-plan"
              >
                <CalendarPlus size={16} />
                {t("meal_planner.new_plan")}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <NativeSelect
              id="meal-plan-picker-plan"
              label={t("meal_planner.select_plan")}
              value={planId}
              onChange={(e) => {
                setPlanId(e.target.value);
                setDate("");
                setSlot("");
              }}
              data-testid="meal-plan-picker-plan"
            >
              <option value="">{t("meal_planner.select_plan")}</option>
              {/* Name and dates, because a plan's name is free text and
                  nothing makes it say anything about time. "Week 2" and
                  "Week 3" only tell them apart for whoever wrote them; the
                  range the plan actually runs over came down with the list
                  and this screen used to drop it. */}
              {plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {`${p.name ?? t("meal_planner.unnamed_plan")} · ${formatDateRange(
                    p.start_date,
                    p.end_date,
                  )}`}
                </option>
              ))}
            </NativeSelect>

            {plan && (
              <>
                <NativeSelect
                  id="meal-plan-picker-day"
                  label={t("meal_planner.select_day")}
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  data-testid="meal-plan-picker-day"
                >
                  <option value="">{t("meal_planner.select_day")}</option>
                  {/* Which weekday it is, since that is the question being
                      answered here — the calendar beside this modal writes
                      its columns the same way. */}
                  {days.map((d) => (
                    <option key={d} value={d}>
                      {format(parseISO(d), "EEE, d MMM", {
                        locale: dateFnsLocale(),
                      })}
                    </option>
                  ))}
                </NativeSelect>

                <NativeSelect
                  id="meal-plan-picker-slot"
                  label={t("meal_planner.select_slot")}
                  value={slot}
                  onChange={(e) => setSlot(e.target.value as MealSlot)}
                  data-testid="meal-plan-picker-slot"
                >
                  <option value="">{t("meal_planner.select_slot")}</option>
                  {plan.enabled_slots.map((s) => (
                    <option key={s} value={s}>
                      {t(`meal_planner.slots.${SLOT_KEYS[s]}`)}
                    </option>
                  ))}
                </NativeSelect>
              </>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={onClose}>
                {t("common:actions.cancel")}
              </Button>
              <Button
                onClick={() => void handleSubmit()}
                disabled={!canSubmit}
                data-testid="meal-plan-picker-submit"
              >
                {submitting ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <CalendarPlus size={16} />
                )}
                {t("meal_planner.add_to_plan")}
              </Button>
            </div>
          </>
        )}
      </SheetBody>
    </Sheet>
  );
}
