import { useState, useEffect } from "react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { addDays, format, isBefore, parseISO, startOfToday } from "date-fns";
import { CalendarX, Copy, Settings } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { invalidation } from "@/lib/api/invalidation";
import {
  extractApiError,
  extractApiErrorCode,
  extractApiErrorRows,
  isNotFoundError,
} from "@/lib/errors";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CopyPlanModal } from "@/modules/recipes/components/CopyPlanModal";
import { MealPlanCalendar } from "@/modules/recipes/components/MealPlanCalendar";
import PickingView from "@/modules/recipes/components/PickingView";
import { RecipePickerModal } from "@/modules/recipes/components/RecipePickerModal";
import { RatingPrompt } from "@/modules/recipes/components/RatingPrompt";
import { ShoppingListPreview } from "@/modules/recipes/components/ShoppingListPreview";
import { DefaultServingsField } from "@/modules/recipes/components/DefaultServingsField";
import { SlotConfigToggle } from "@/modules/recipes/components/SlotConfigToggle";
import {
  useMealPlan,
  useAddMealPlanEntry,
  useDeleteMealPlanEntry,
  useUpdateMealPlan,
  useUpdateMealPlanEntry,
  useCopyPlanToWeek,
  useGenerateMealPlanShoppingList,
} from "@/modules/recipes/hooks/useMealPlans";
import { usePatchCookingHistory } from "@/modules/recipes/hooks/useRecipes";
import type {
  MealPlanEntry,
  MealSlot,
  ShoppingListGenerationResult,
} from "@/modules/recipes/types/mealplans";
import { DailyNutritionCard } from "@/modules/recipes/components/DailyNutritionCard";

interface PickerState {
  date: string;
  slot: MealSlot;
}

interface RatingPromptState {
  sessionId: string;
  recipeId: string;
  recipeName: string;
}

interface SlotConflict {
  slot: MealSlot;
  count: number;
}

interface SlotConflictState {
  slots: MealSlot[];
  conflicts: SlotConflict[];
}

/**
 * The per-slot `conflicts` rows the API attaches to a 409 detail.
 *
 * Reading the envelope is `extractApiErrorRows`'s job — what is left here
 * is the part only this screen knows: a conflict row is a slot and a count.
 */
function readSlotConflicts(error: unknown): SlotConflict[] {
  const rows = extractApiErrorRows(error, "conflicts") ?? [];
  return rows.filter(
    (row): row is { slot: MealSlot; count: number } =>
      typeof row.slot === "string" && typeof row.count === "number",
  );
}

/** Copying needs a meal to copy; the reason is text, not only a title. */
function CopyPlanButton({
  hasMeals,
  onCopy,
  t,
}: {
  hasMeals: boolean;
  onCopy: () => void;
  t: TFunction;
}) {
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={onCopy}
        disabled={!hasMeals}
        aria-describedby={hasMeals ? undefined : "meal-plan-needs-meals"}
        leftIcon={<Copy size={16} />}
      >
        {t("meal_planner.copy_to_week")}
      </Button>
      {!hasMeals && (
        <p id="meal-plan-needs-meals" className="text-xs text-on-muted">
          {t("meal_planner.needs_meals_hint")}
        </p>
      )}
    </div>
  );
}

export default function MealPlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation("recipes");

  const [pickerState, setPickerState] = useState<PickerState | null>(null);
  const [cookEntry, setCookEntry] = useState<MealPlanEntry | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showCopy, setShowCopy] = useState(false);
  const [copyStart, setCopyStart] = useState("");
  const [copyEnd, setCopyEnd] = useState("");
  const [ratingPrompt, setRatingPrompt] = useState<RatingPromptState | null>(
    null,
  );
  const [shoppingResult, setShoppingResult] = useState<
    ShoppingListGenerationResult | undefined
  >();
  const [slotConflict, setSlotConflict] = useState<SlotConflictState | null>(
    null,
  );

  const {
    data: plan,
    isLoading,
    isError,
    error,
    refetch,
  } = useMealPlan(id ?? "");
  const queryClient = useQueryClient();
  const addEntry = useAddMealPlanEntry();
  const removeEntry = useDeleteMealPlanEntry();
  const updatePlan = useUpdateMealPlan();
  const updateEntry = useUpdateMealPlanEntry();
  const copyPlan = useCopyPlanToWeek();
  const generateList = useGenerateMealPlanShoppingList();
  const patchHistory = usePatchCookingHistory(ratingPrompt?.recipeId ?? "");

  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("recipes");

  // Depend on what the title is made of, never on the plan object: the query
  // hands back a fresh reference on every refetch, and this effect calls
  // setHeader, so an object dependency renders in a loop.
  const planName = plan?.name;
  const planArrived = plan !== undefined;

  useEffect(() => {
    setHeader({
      // "Unnamed Plan" is a statement about a plan, and only a plan
      // that arrived can support it. Until then the section names
      // itself and claims nothing about the record.
      title: planArrived
        ? planName || t("meal_planner.unnamed_plan")
        : t("meal_planner.page_title"),
      backTo: "/recipes/meal-planner",
      // The panel behind it only holds controls that save on change.
      actions: canWrite ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowSettings((p) => !p)}
          aria-label={t("meal_planner.open_settings")}
        >
          <Settings size={16} />
        </Button>
      ) : undefined,
    });
  }, [planName, planArrived, t, setHeader, canWrite]);

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!plan) {
    return (
      <RecordNotFound
        icon={CalendarX}
        title={t("meal_planner.plan_not_found")}
        backTo="/recipes/meal-planner"
        backLabel={t("meal_planner.back_to_plans")}
      />
    );
  }

  async function handleAddEntry(recipeId: string) {
    if (!pickerState || !id) return;
    try {
      await addEntry.mutateAsync({
        planId: id,
        data: {
          date: pickerState.date,
          slot: pickerState.slot,
          recipe_id: recipeId,
        },
      });
      setPickerState(null);
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.entry_add_error")));
    }
  }

  async function handleRemoveEntry(entryId: string) {
    if (!id) return;
    try {
      await removeEntry.mutateAsync({ planId: id, entryId });
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.entry_remove_error")));
    }
  }

  function handleCookEntry(entryId: string) {
    const entry = plan?.entries.find((e) => e.id === entryId);
    if (entry) setCookEntry(entry);
  }

  function handleCookClose(completed?: boolean, sessionId?: string) {
    const entry = cookEntry;
    setCookEntry(null);
    if (completed && entry && id) {
      // Refresh the plan so the entry's is_completed flag updates, then ask
      // for a rating — the picking session is completed at this point, so the
      // history PATCH accepts it.
      invalidation.mealPlans(queryClient, id);
      if (sessionId) {
        setRatingPrompt({
          sessionId,
          recipeId: entry.recipe_id,
          recipeName: entry.recipe_name,
        });
      }
    }
  }

  async function handleRate(rating: number) {
    if (!ratingPrompt) return;
    try {
      await patchHistory.mutateAsync({
        sessionId: ratingPrompt.sessionId,
        data: { rating },
      });
      toast.success(t("meal_planner.rate_success"));
      setRatingPrompt(null);
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.rate_error")));
    }
  }

  async function handleMoveEntry(
    entryId: string,
    date: string,
    slot: MealSlot,
  ) {
    if (!id) return;
    try {
      await updateEntry.mutateAsync({
        planId: id,
        entryId,
        data: { date, slot },
      });
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.entry_move_error")));
    }
  }

  async function handleSlotChange(slots: MealSlot[]) {
    if (!id) return;
    try {
      await updatePlan.mutateAsync({ id, data: { enabled_slots: slots } });
    } catch (error) {
      if (extractApiErrorCode(error) === "MEAL_PLAN_SLOT_CONFLICT") {
        // the API answers 409 with per-slot conflicts — let the user
        // decide instead of failing silently and snapping the toggle back.
        setSlotConflict({ slots, conflicts: readSlotConflicts(error) });
      } else {
        toast.error(t("meal_planner.update_error"));
      }
    }
  }

  async function handleDefaultServingsChange(servings: number | undefined) {
    if (!id) return;
    try {
      await updatePlan.mutateAsync({
        id,
        data: { default_servings: servings },
      });
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.update_error")));
    }
  }

  async function confirmSlotConflict() {
    if (!id || !slotConflict) return;
    try {
      await updatePlan.mutateAsync({
        id,
        data: {
          enabled_slots: slotConflict.slots,
          remove_conflicting_entries: true,
        },
      });
      setSlotConflict(null);
    } catch (error) {
      setSlotConflict(null);
      toast.error(extractApiError(error, t("meal_planner.update_error")));
    }
  }

  const openCopyModal = () => {
    if (!plan) return;
    // Default: the week right after the current plan range, clamped to
    // today — the backend rejects target start dates in the past.
    const afterPlan = addDays(parseISO(plan.end_date), 1);
    const start = isBefore(afterPlan, startOfToday())
      ? startOfToday()
      : afterPlan;
    const spanDays = Math.max(
      0,
      Math.min(
        13,
        Math.round(
          (parseISO(plan.end_date).getTime() -
            parseISO(plan.start_date).getTime()) /
            86400000,
        ),
      ),
    );
    setCopyStart(format(start, "yyyy-MM-dd"));
    setCopyEnd(format(addDays(start, spanDays), "yyyy-MM-dd"));
    setShowCopy(true);
  };

  async function handleCopyToWeek() {
    if (!id || !copyStart || !copyEnd) return;
    if (copyEnd < copyStart) {
      toast.error(t("meal_planner.copy_error"));
      return;
    }
    try {
      const result = await copyPlan.mutateAsync({
        planId: id,
        data: { start_date: copyStart, end_date: copyEnd },
      });
      toast.success(
        [
          t("meal_planner.copy_copied", { count: result.copied }),
          t("meal_planner.copy_skipped", { count: result.skipped }),
        ].join(", "),
      );
      setShowCopy(false);
      // The copy is a new plan covering the target range — take the user
      // there so the copied entries are visible.
      navigate(`/recipes/meal-planner/${result.plan.id}`);
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.copy_error")));
    }
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <ReadOnlyNotice module="recipes" />
      {showSettings && canWrite && (
        <div className="rounded-lg border border-border p-4 flex flex-col gap-2">
          <SlotConfigToggle
            label={t("meal_planner.enabled_slots")}
            enabledSlots={plan.enabled_slots}
            onChange={handleSlotChange}
            t={t}
            disabled={updatePlan.isPending}
          />

          <DefaultServingsField
            value={plan.default_servings ?? undefined}
            onChange={handleDefaultServingsChange}
            disabled={updatePlan.isPending}
          />
        </div>
      )}

      <ShoppingListPreview
        canWrite={canWrite}
        planId={id ?? ""}
        hasMeals={plan.entries.length > 0}
        existingListId={plan.shopping_list_id}
        mealsAddedSinceList={plan.meals_added_since_list}
        generationResult={shoppingResult}
        isGenerating={generateList.isPending}
        onGenerate={() => {
          generateList
            .mutateAsync(id ?? "")
            .then(setShoppingResult, (error) => {
              toast.error(
                extractApiError(error, t("meal_planner.generate_error")),
              );
            });
        }}
        t={t}
      />

      {canWrite && (
        <CopyPlanButton
          hasMeals={plan.entries.length > 0}
          onCopy={openCopyModal}
          t={t}
        />
      )}

      <MealPlanCalendar
        plan={plan}
        canWrite={canWrite}
        onAddEntry={(date, slot) => setPickerState({ date, slot })}
        onRemoveEntry={handleRemoveEntry}
        onCookEntry={handleCookEntry}
        onMoveEntry={handleMoveEntry}
        t={t}
      />

      <DailyNutritionCard days={plan.daily_nutrition_summary} />

      {pickerState && (
        <RecipePickerModal
          isOpen
          date={pickerState.date}
          slot={pickerState.slot}
          planId={id ?? ""}
          canWrite={canWrite}
          onSelect={handleAddEntry}
          onClose={() => setPickerState(null)}
        />
      )}

      {/* The picking screens bring their own sheets. Wrapped in one more
          here, its backdrop stood above the checklist and every tap on it
          closed the flow. */}
      {cookEntry && (
        <PickingView
          recipeId={cookEntry.recipe_id}
          recipeName={cookEntry.recipe_name}
          defaultServings={
            cookEntry.servings || plan.default_servings || undefined
          }
          mealPlanEntryId={cookEntry.id}
          onClose={handleCookClose}
        />
      )}

      {ratingPrompt && (
        <RatingPrompt
          open
          recipeName={ratingPrompt.recipeName}
          isSaving={patchHistory.isPending}
          onRate={handleRate}
          onSkip={() => setRatingPrompt(null)}
          t={t}
        />
      )}

      {showCopy && (
        <CopyPlanModal
          copyStart={copyStart}
          copyEnd={copyEnd}
          isPending={copyPlan.isPending}
          onStartChange={setCopyStart}
          onEndChange={setCopyEnd}
          onConfirm={handleCopyToWeek}
          onClose={() => setShowCopy(false)}
          t={t}
        />
      )}

      {slotConflict && (
        <ConfirmDialog
          open
          variant="warning"
          title={t("meal_planner.slot_conflict_title")}
          message={t("meal_planner.slot_conflict_explanation")}
          confirmLabel={t("meal_planner.slot_conflict_confirm")}
          onConfirm={confirmSlotConflict}
          onCancel={() => setSlotConflict(null)}
        >
          <ul className="space-y-1">
            {slotConflict.conflicts.map((conflict) => (
              <li
                key={conflict.slot}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <span className="font-medium">
                  {t(
                    `meal_planner.slots.${conflict.slot.toLowerCase()}` as const,
                  )}
                </span>
                <span className="text-on-secondary tabular-nums">
                  {t("meal_planner.slot_conflict_entries", {
                    count: conflict.count,
                  })}
                </span>
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </div>
  );
}
