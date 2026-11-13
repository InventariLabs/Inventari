import { useDraggable } from "@dnd-kit/core";

import { DND_LABEL } from "@/lib/dndA11y";
import { CSS } from "@dnd-kit/utilities";
import { CheckCircle, ChefHat, GripVertical, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useHasPermission } from "@/hooks/useHasPermission";
import { cn } from "@/lib/utils";
import type { MealPlanEntry } from "@/modules/recipes/types/mealplans";

interface MealPlanEntryCardProps {
  entry: MealPlanEntry;
  isPast: boolean;
  /** Whether to offer cooking, removing and dragging the entry. */
  canWrite?: boolean;
  onCook: (id: string) => void;
  onRemove: (id: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

/**
 * MealPlanEntryCard — a single meal plan entry.
 *
 * Draggable so it can be moved to another (date, slot) cell. Drag starts from
 * the grip handle (listeners live on the handle, not the whole card, so the
 * cook/remove buttons keep working).
 */
export function MealPlanEntryCard({
  entry,
  isPast,
  canWrite = true,
  onCook,
  onRemove,
  t,
}: MealPlanEntryCardProps) {
  // Cooking checks `recipes:consume`, not the plan's `recipes:write`: the
  // person at the stove and the person planning the week are different
  // grants, and the card used to spell both with one prop.
  const canConsume = useHasPermission("recipes:consume");
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id: entry.id,
      data: { type: "meal-plan-entry", [DND_LABEL]: entry.recipe_name },
    });

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? "var(--z-sticky)" : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded border p-1.5 flex flex-col gap-0.5 relative",
        isPast
          ? "bg-surface-inset/30 border-border/50"
          : "bg-surface-card border-border",
        entry.is_completed && "border-accent/50",
        isDragging && "shadow-lg ring-1 ring-primary/40",
      )}
    >
      {entry.is_completed && (
        <CheckCircle
          size={12}
          className="absolute top-1 right-1 text-accent"
          aria-label={t("recipes:meal_planner.completed")}
        />
      )}

      {/* The name block carries the remove button beside it: tall enough that
          the button's 44px box ends before the row below starts. Without the
          floor, a one-line name put the corner button and the drag handle
          three pixels apart — two destructive-adjacent controls a single
          thumb could cover. */}
      <p className="text-xs font-medium leading-tight line-clamp-2 pr-11 md:pr-9 min-h-11 md:min-h-8">
        {entry.recipe_name}
      </p>

      <p className="text-xs text-on-muted">
        {t("recipes:meal_planner.servings", { count: entry.servings })}
      </p>

      {isPast && !entry.is_completed && (
        <p className="text-xs text-on-muted/70 italic">
          {t("recipes:meal_planner.not_cooked")}
        </p>
      )}

      {/* Remove lives in the corner, not in the row with the drag handle:
          two 16px controls side by side meant a thumb aiming at the handle
          pressed "remove this meal", and the destructive one was the one
          on the right. The card has room — this row only appears in the
          phone's day view, where a cell is the full width of the screen. */}
      {!isPast && !entry.is_completed && canWrite && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => onRemove(entry.id)}
          // Named after its meal: a week of cards read as one "Remove meal
          // from plan" after another, with nothing telling them apart.
          aria-label={t("recipes:meal_planner.remove_entry_named", {
            recipe: entry.recipe_name,
          })}
          title={t("recipes:meal_planner.remove_entry")}
          className="absolute right-0.5 top-0.5 text-on-muted hover:text-on-danger md:h-8 md:w-8"
        >
          <X size={16} aria-hidden="true" />
        </Button>
      )}

      {!isPast && !entry.is_completed && canWrite && (
        <div className="flex flex-wrap items-center gap-1 mt-auto pt-0.5">
          {canConsume && (
            <Button
              size="content"
              type="button"
              variant="link"
              onClick={() => onCook(entry.id)}
              aria-label={t("recipes:meal_planner.cook_now_named", {
                recipe: entry.recipe_name,
              })}
              className="p-0 text-xs text-accent-700 gap-0.5 min-h-11 md:min-h-8"
            >
              <ChefHat size={16} />
              {t("recipes:meal_planner.cook_now")}
            </Button>
          )}
          {!isPast && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              {...attributes}
              {...listeners}
              // The calendar finds this handle by the entry it moves, to give
              // the keyboard back the place it lost when the card remounted in
              // another cell (see MealPlanCalendar's entryToRefocus).
              data-entry-handle={entry.id}
              aria-label={t("recipes:meal_planner.drag_to_move_named", {
                recipe: entry.recipe_name,
              })}
              title={t("recipes:meal_planner.drag_to_move")}
              className="ml-auto text-on-muted hover:text-on cursor-grab active:cursor-grabbing touch-none hover:bg-transparent md:h-8 md:w-8"
            >
              <GripVertical size={16} />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
