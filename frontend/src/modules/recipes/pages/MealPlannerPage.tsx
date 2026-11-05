import { extractApiError } from "@/lib/errors";
import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { addDays, format, parseISO } from "date-fns";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useTranslation } from "react-i18next";
import { Plus, Calendar } from "lucide-react";
import { toast } from "sonner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useModules } from "@/contexts/ModulesContext";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { MealPlanCard } from "@/modules/recipes/components/MealPlanCard";
import { DefaultServingsField } from "@/modules/recipes/components/DefaultServingsField";
import { SlotConfigToggle } from "@/modules/recipes/components/SlotConfigToggle";
import {
  useMealPlans,
  useAddMealPlanEntry,
  useCreateMealPlan,
  useDeleteMealPlan,
  useGenerateMealPlanShoppingList,
} from "@/modules/recipes/hooks/useMealPlans";
import type {
  MealPlanCreate,
  MealPlanListItem,
  MealSlot,
} from "@/modules/recipes/types/mealplans";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { todayIso } from "@/utils/formatters";
import { onOtherListsMessage } from "@/modules/shared/lib/shoppingOverlap";

const DEFAULT_SLOTS: MealSlot[] = ["BREAKFAST", "LUNCH", "DINNER"];
const SLOT_ORDER: MealSlot[] = [...DEFAULT_SLOTS, "SNACK"];

/**
 * A new plan runs from the reader's today through six days later — both
 * ends saved, so both ends are calendar days: `toISOString()` answers in
 * UTC, which east of Greenwich just after midnight is yesterday.
 */
function getDefaultDates() {
  const start = todayIso();
  return { start, end: format(addDays(parseISO(start), 6), "yyyy-MM-dd") };
}

export default function MealPlannerPage() {
  const { t } = useTranslation("recipes");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("recipes");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [planToDelete, setPlanToDelete] = useState<MealPlanListItem | null>(
    null,
  );
  const [formName, setFormName] = useState("");
  const { start, end } = getDefaultDates();
  const [formStart, setFormStart] = useState(start);
  const [formEnd, setFormEnd] = useState(end);
  const [formSlots, setFormSlots] = useState<MealSlot[]>(DEFAULT_SLOTS);
  const [formServings, setFormServings] = useState<number | undefined>(
    undefined,
  );

  const {
    data: plans = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useMealPlans();
  const createPlan = useCreateMealPlan();
  const addEntry = useAddMealPlanEntry();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // A recipe that sent the reader here to make its first plan ("?recipe=")
  // goes onto that plan once it exists.
  const [recipeForNewPlan, setRecipeForNewPlan] = useState<string | null>(null);
  // The plan that exists once its first write has succeeded, and where the
  // recipe goes on it. While the recipe is not placed the form stays open
  // and "Create" retries the placement — never a second plan.
  const [placement, setPlacement] = useState<{
    planId: string;
    recipeId: string;
    date: string;
    slot: MealSlot;
  } | null>(null);
  const deletePlan = useDeleteMealPlan();
  const generateList = useGenerateMealPlanShoppingList();
  // the shopping-list actions write to a possibly disabled module —
  // gate them so they cannot "succeed" into an unreachable list.
  const { isModuleEnabled } = useModules();
  const shoppingListsEnabled = isModuleEnabled("shopping_lists");

  function openCreateModal() {
    const defaults = getDefaultDates();
    setFormName("");
    setFormStart(defaults.start);
    setFormEnd(defaults.end);
    setFormSlots(DEFAULT_SLOTS);
    setFormServings(undefined);
    setRecipeForNewPlan(null);
    setPlacement(null);
    setShowCreateModal(true);
  }

  // A screen that cannot place a recipe because no plan exists sends the
  // reader here with "?new=1" — the form opens on arrival instead of asking
  // them to find the button they were just promised.
  useEffect(() => {
    if (searchParams.get("new") !== "1") return;
    if (canWrite) {
      setRecipeForNewPlan(searchParams.get("recipe"));
      setPlacement(null);
      setShowCreateModal(true);
    }
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    next.delete("recipe");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, canWrite]);

  useEffect(() => {
    setHeader({
      title: t("meal_planner.page_title"),
      // Header CTA only when there are plans — the empty state has its own
      actions:
        plans.length > 0 && canWrite ? (
          <Button onClick={openCreateModal} size="sm">
            <Plus size={16} className="mr-1" />
            {t("meal_planner.new_plan")}
          </Button>
        ) : undefined,
    });
  }, [t, setHeader, plans.length, canWrite]);

  async function handleCreate() {
    if (formSlots.length === 0) {
      toast.error(t("meal_planner.slots_required"));
      return;
    }
    const data: MealPlanCreate = {
      name: formName || undefined,
      start_date: formStart,
      end_date: formEnd,
      enabled_slots: formSlots,
      default_servings: formServings,
    };
    try {
      let target = placement;
      if (!target) {
        const plan = await createPlan.mutateAsync(data);
        toast.success(t("meal_planner.plan_created"));
        const slot = SLOT_ORDER.find((s) => formSlots.includes(s));
        if (recipeForNewPlan && slot) {
          target = {
            planId: plan.id,
            recipeId: recipeForNewPlan,
            date: formStart,
            slot,
          };
          setPlacement(target);
        } else {
          setShowCreateModal(false);
          return;
        }
      }
      if (!(await placeRecipe(target))) return;
      setShowCreateModal(false);
      navigate(`/recipes/meal-planner/${target.planId}`);
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.create_error")));
    }
  }

  /** The first day and first meal of the new plan; the calendar moves it. */
  async function placeRecipe(target: NonNullable<typeof placement>) {
    try {
      await addEntry.mutateAsync({
        planId: target.planId,
        data: {
          date: target.date,
          slot: target.slot,
          recipe_id: target.recipeId,
        },
      });
      toast.success(t("meal_planner.added_to_plan"));
      return true;
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
      return false;
    }
  }

  async function handleDelete(plan: MealPlanListItem) {
    setPlanToDelete(null);
    try {
      await deletePlan.mutateAsync(plan.id);
      toast.success(t("meal_planner.plan_deleted"));
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.delete_error")));
    }
  }

  async function handleGenerateList(id: string) {
    try {
      const result = await generateList.mutateAsync(id);
      toast.success(t("meal_planner.list_generated"));
      // The same goods may already stand on another open list.
      const overlap = onOtherListsMessage(t, result.on_other_lists);
      if (overlap) toast.warning(overlap);
    } catch (error) {
      toast.error(extractApiError(error, t("meal_planner.generate_error")));
    }
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <ReadOnlyNotice module="recipes" />
      {isError && <QueryFailure error={error} onRetry={() => refetch()} />}

      {!isError && isLoading && <LoadingSpinner />}

      {!isError && !isLoading && plans.length === 0 && (
        <EmptyState
          icon={Calendar}
          title={t("meal_planner.no_plans")}
          description={t("meal_planner.no_plans_description")}
          primaryAction={
            canWrite ? (
              <Button onClick={openCreateModal} variant="outline" size="sm">
                <Plus size={16} className="mr-1" />
                {t("meal_planner.new_plan")}
              </Button>
            ) : undefined
          }
        />
      )}

      {/* auto-fit — a single plan stretches across the width instead
          of leaving two empty columns; more plans wrap into equal tracks. */}
      <div className="grid grid-cols-1 sm:grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-4">
        {plans.map((plan) => (
          <MealPlanCard
            key={plan.id}
            canWrite={canWrite}
            plan={plan}
            onDelete={(id) =>
              setPlanToDelete(plans.find((p) => p.id === id) ?? null)
            }
            onGenerateShoppingList={handleGenerateList}
            shoppingListsEnabled={shoppingListsEnabled}
            t={t}
          />
        ))}
      </div>

      {planToDelete && (
        <ConfirmDialog
          open
          variant="danger"
          title={t("meal_planner.delete_plan_confirm_title")}
          message={
            planToDelete.entry_count > 0
              ? t("meal_planner.delete_plan_confirm", {
                  count: planToDelete.entry_count,
                })
              : t("meal_planner.delete_plan_confirm_empty")
          }
          confirmLabel={t("meal_planner.delete_plan")}
          onConfirm={() => handleDelete(planToDelete)}
          onCancel={() => setPlanToDelete(null)}
        />
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <Sheet
          open
          onClose={() => setShowCreateModal(false)}
          zIndex="confirm"
          maxWidth="md"
          aria-label={t("meal_planner.new_plan")}
        >
          <SheetHeader
            title={t("meal_planner.new_plan")}
            onClose={() => setShowCreateModal(false)}
          />

          <SheetBody className="p-6 flex flex-col gap-4">
            <Input
              label={t("meal_planner.plan_name_optional")}
              placeholder={t("meal_planner.plan_name_placeholder")}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
            />

            <div className="flex gap-3">
              <DateInput
                label={t("meal_planner.start_date")}
                value={formStart}
                onChange={(e) => setFormStart(e)}
                wrapperClassName="flex-1"
              />
              <DateInput
                label={t("meal_planner.end_date")}
                value={formEnd}
                onChange={(e) => setFormEnd(e)}
                wrapperClassName="flex-1"
              />
            </div>

            <SlotConfigToggle
              label={t("meal_planner.slots_label")}
              enabledSlots={formSlots}
              onChange={setFormSlots}
              t={t}
            />

            <DefaultServingsField
              value={formServings}
              onChange={setFormServings}
            />
          </SheetBody>

          <FormSheetFooter
            isPending={createPlan.isPending || addEntry.isPending}
            lineCount={0}
            cancelText={t("common:form.cancel")}
            submitText={t("meal_planner.create")}
            onCancel={() => setShowCreateModal(false)}
            onSubmit={handleCreate}
          />
        </Sheet>
      )}
    </div>
  );
}
