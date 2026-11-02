import { useDroppable } from "@dnd-kit/core";
import { format, parseISO } from "date-fns";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { dateFnsLocale } from "@/utils/formatters";
import { DND_LABEL } from "@/lib/dndA11y";
import { MealPlanEntryCard } from "./MealPlanEntryCard";
import type {
  MealPlanEntry,
  MealSlot,
} from "@/modules/recipes/types/mealplans";

interface MealPlanCellProps {
  date: string;
  slot: MealSlot;
  /** The slot's name in the interface language — the row header uses it too. */
  slotLabel: string;
  entries: MealPlanEntry[];
  isPast: boolean;
  /** Whether the reader may change the plan. A reader's cell is inert. */
  canWrite?: boolean;
  onAdd: (date: string, slot: MealSlot) => void;
  onRemove: (entryId: string) => void;
  onCook: (entryId: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function MealPlanCell({
  date,
  slot,
  slotLabel,
  entries,
  isPast,
  canWrite = true,
  onAdd,
  onRemove,
  onCook,
  t,
}: MealPlanCellProps) {
  // A cell nobody can put a meal in: past, or an account that may not plan.
  // The two produce the same inert cell, so they share one name here — but
  // only here, because "you missed it" and "you may not" are different
  // sentences and the entry card still tells them apart.
  const locked = isPast || !canWrite;

  const { setNodeRef, isOver } = useDroppable({
    id: `${date}::${slot}`,
    data: {
      type: "meal-plan-cell",
      date,
      slot,
      isPast,
      [DND_LABEL]: `${slotLabel}, ${format(parseISO(date), "EEEE d MMM", { locale: dateFnsLocale() })}`,
    },
    disabled: locked,
  });

  // Drop zone highlight — only for valid targets (future/present cells).
  const highlightDrop = isOver && !locked;

  // Twenty-one buttons in this grid, and they used to share one name: "Add a
  // meal to this slot". Which slot is exactly what a reader who cannot see the
  // grid needs to be told.
  const addLabel = t("recipes:meal_planner.add_to_slot_named", {
    slot: slotLabel,
    day: format(parseISO(date), "EEEE d MMM", { locale: dateFnsLocale() }),
  });

  if (entries.length === 0) {
    return (
      <div
        ref={setNodeRef}
        role={locked ? undefined : "button"}
        tabIndex={locked ? undefined : 0}
        aria-label={locked ? undefined : addLabel}
        className={cn(
          "min-h-[72px] rounded-lg border border-dashed flex items-center justify-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          locked
            ? "border-border/30 bg-surface-inset/40"
            : "border-border hover:border-accent hover:bg-accent/5 cursor-pointer group",
          highlightDrop && "border-accent bg-accent/10 ring-1 ring-accent/40",
        )}
        onClick={locked ? undefined : () => onAdd(date, slot)}
        onKeyDown={
          locked
            ? undefined
            : (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onAdd(date, slot);
                }
              }
        }
      >
        {!locked && (
          <Plus
            size={18}
            aria-hidden="true"
            className="text-on-muted group-hover:text-accent transition-colors"
          />
        )}
      </div>
    );
  }

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "min-h-[72px] rounded-lg flex flex-col gap-1 p-0.5 -m-0.5 transition-colors",
        highlightDrop && "bg-accent/10 ring-1 ring-accent/40 rounded-lg",
      )}
    >
      {entries.map((entry) => (
        <MealPlanEntryCard
          key={entry.id}
          entry={entry}
          isPast={isPast}
          canWrite={canWrite}
          onCook={onCook}
          onRemove={onRemove}
          t={t}
        />
      ))}
      {!locked && (
        <Button
          size="content"
          type="button"
          variant="ghost"
          aria-label={addLabel}
          title={addLabel}
          onClick={() => onAdd(date, slot)}
          className="w-full p-0.5 rounded border border-dashed border-border/50 hover:border-accent min-h-11 md:min-h-8"
        >
          <Plus size={16} aria-hidden="true" className="text-on-muted" />
        </Button>
      )}
    </div>
  );
}
