import { useId } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { FIELD_LABEL_CLASS } from "@/components/ui/fieldLabel";
import type { MealSlot } from "@/modules/recipes/types/mealplans";

const SLOT_ORDER: MealSlot[] = ["BREAKFAST", "LUNCH", "DINNER", "SNACK"];

interface SlotConfigToggleProps {
  enabledSlots: MealSlot[];
  onChange: (slots: MealSlot[]) => void;
  t: (key: string) => string;
  disabled?: boolean;
  /**
   * Names the whole group, the way `ChoiceGroup` does for a single choice.
   * Both call sites used to place a `<label>` above these chips — a label can
   * only name one form control, so it named nothing and a reader heard four
   * meal slots with no idea what question they answered.
   */
  label?: string;
}

export function SlotConfigToggle({
  enabledSlots,
  onChange,
  t,
  disabled,
  label,
}: SlotConfigToggleProps) {
  const labelId = useId();

  function toggle(slot: MealSlot) {
    if (enabledSlots.includes(slot)) {
      onChange(enabledSlots.filter((s) => s !== slot));
    } else {
      onChange(
        [...enabledSlots, slot].sort(
          (a, b) => SLOT_ORDER.indexOf(a) - SLOT_ORDER.indexOf(b),
        ),
      );
    }
  }

  return (
    <div className="w-full space-y-1.5">
      {label && (
        <p id={labelId} className={FIELD_LABEL_CLASS}>
          {label}
        </p>
      )}
      <div
        role="group"
        aria-labelledby={label ? labelId : undefined}
        className="flex flex-wrap gap-2"
      >
        {SLOT_ORDER.map((slot) => {
          const active = enabledSlots.includes(slot);
          return (
            <Button
              size="content"
              key={slot}
              type="button"
              variant="outline"
              disabled={disabled}
              aria-pressed={active}
              onClick={() => toggle(slot)}
              className={cn(
                "px-3 py-1.5 rounded-full text-xs transition-colors",
                active
                  ? "bg-primary-50 border-primary-500 text-on font-medium"
                  : "bg-surface text-on-muted border-border hover:bg-surface-inset",
                "disabled:cursor-not-allowed disabled:pointer-events-auto",
              )}
            >
              {t(`meal_planner.slots.${slot.toLowerCase()}`)}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
