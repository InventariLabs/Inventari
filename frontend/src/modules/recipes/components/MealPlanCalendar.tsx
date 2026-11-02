import { Fragment, useEffect, useState } from "react";
import { format, addDays, parseISO, isBefore, startOfToday } from "date-fns";
import { DndContext, type DragEndEvent } from "@dnd-kit/core";
import { MealPlanScroller } from "./MealPlanScroller";
import { MealPlanCell } from "./MealPlanCell";
import type {
  MealPlan,
  MealPlanEntry,
  MealSlot,
} from "@/modules/recipes/types/mealplans";
import { dateFnsLocale } from "@/utils/formatters";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useDndA11y, useDndSensors } from "@/lib/dndA11y";

interface MealPlanCalendarProps {
  plan: MealPlan;
  /** Whether the reader may change the plan; threaded to every cell. */
  canWrite?: boolean;
  onAddEntry: (date: string, slot: MealSlot) => void;
  onRemoveEntry: (entryId: string) => void;
  onCookEntry: (entryId: string) => void;
  onMoveEntry: (entryId: string, date: string, slot: MealSlot) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

const SLOT_ORDER: MealSlot[] = ["BREAKFAST", "LUNCH", "DINNER", "SNACK"];

function getDaysInRange(startDate: string, endDate: string): Date[] {
  const days: Date[] = [];
  const start = parseISO(startDate);
  const end = parseISO(endDate);
  let current = start;
  while (current <= end) {
    days.push(current);
    current = addDays(current, 1);
  }
  return days;
}

export function MealPlanCalendar({
  plan,
  canWrite = true,
  onAddEntry,
  onRemoveEntry,
  onCookEntry,
  onMoveEntry,
  t,
}: MealPlanCalendarProps) {
  /**
   * A week laid out across the screen is a desktop shape. At 390px the grid
   * showed two and a half days of seven — 562 of its 928 pixels off-screen —
   * and the whole point of this screen is to see the week: where the gaps
   * are, what repeats. A scroll cue does not fix that; the axis has to turn.
   *
   * Rendered once per viewport size (useMediaQuery), the way the
   * purchase-order row picks between its two shapes, so the desktop grid stays
   * exactly as it was and stays testable in jsdom.
   */
  const isNarrow = useMediaQuery("(max-width: 767px)");
  const days = getDaysInRange(plan.start_date, plan.end_date);
  const today = startOfToday();
  const activeSlots = SLOT_ORDER.filter((s) => plan.enabled_slots.includes(s));

  const entriesBySlotAndDate = new Map<string, MealPlanEntry[]>();
  for (const entry of plan.entries) {
    const key = `${entry.date}::${entry.slot}`;
    const list = entriesBySlotAndDate.get(key) ?? [];
    list.push(entry);
    entriesBySlotAndDate.set(key, list);
  }

  // This calendar is drag-into-target: entries are useDraggable, cells are
  // useDroppable, and nothing here is sortable. Asking the keyboard for
  // sortable coordinates resolves the lifted entry against a SortableContext
  // that does not exist on this screen, so the getter answered undefined —
  // the space bar lifted the entry and the arrows never moved it. A
  // drag-into-target context keeps the library's default coordinates.
  const sensors = useDndSensors(6, false);
  const dndA11y = useDndA11y();

  // Where the focus should go back to, and where the entry has to be drawn
  // before it can: a move to another cell remounts the card there, so the node
  // the reader was standing on is gone when the drop lands and focus falls to
  // the body (measured at 1440 and at 390: `document.activeElement` was `BODY`
  // after the move, while a drop in the same cell left focus on the grip). The
  // move is optimistic, so the destination is only drawn in a later render —
  // the cell is remembered too, because until the entry appears in it the old
  // node is still on screen and focusing that one would be focusing a ghost.
  const [entryToRefocus, setEntryToRefocus] = useState<{
    id: string;
    date: string;
    slot: MealSlot;
  } | null>(null);

  useEffect(() => {
    if (!entryToRefocus) return;
    const landed = plan.entries.some(
      (candidate) =>
        candidate.id === entryToRefocus.id &&
        candidate.date === entryToRefocus.date &&
        candidate.slot === entryToRefocus.slot,
    );
    if (!landed) return;
    const handle = document.querySelector<HTMLElement>(
      `[data-entry-handle="${entryToRefocus.id}"]`,
    );
    if (!handle) return;
    handle.focus();
    setEntryToRefocus(null);
  }, [entryToRefocus, plan.entries]);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const overData = over.data.current as
      | { type?: string; date?: string; slot?: MealSlot; isPast?: boolean }
      | undefined;
    if (overData?.type !== "meal-plan-cell") return;
    if (overData.isPast || !overData.date || !overData.slot) return;
    const entryId = String(active.id);
    const entry = plan.entries.find((candidate) => candidate.id === entryId);
    onMoveEntry(entryId, overData.date, overData.slot);
    // Only a move to another cell remounts the card. A drop in place leaves the
    // reader's focus exactly where they had it.
    if (
      entry &&
      (entry.date !== overData.date || entry.slot !== overData.slot)
    ) {
      setEntryToRefocus({
        id: entryId,
        date: overData.date,
        slot: overData.slot,
      });
    }
  }

  if (isNarrow) {
    return (
      <DndContext
        sensors={sensors}
        onDragEnd={handleDragEnd}
        accessibility={dndA11y}
      >
        {/* One day at a time, each meal on a full-width row. Meals side by
            side would leave a cell 85px on a phone — narrower than the grid
            this replaces — and a plan can carry four of them. */}
        <div className="space-y-5">
          {days.map((day) => {
            const dateStr = format(day, "yyyy-MM-dd");
            const isPast = isBefore(day, today);
            return (
              <section key={dateStr} className="space-y-2">
                <h3 className="flex items-baseline gap-2 border-b border-border pb-1">
                  <span className="text-xs font-medium uppercase text-on-muted">
                    {format(day, "EEE", { locale: dateFnsLocale() })}
                  </span>
                  <span className="text-sm font-semibold text-on">
                    {format(day, "d MMM", { locale: dateFnsLocale() })}
                  </span>
                </h3>
                {activeSlots.map((slot) => {
                  const slotLabel = t(
                    `meal_planner.slots.${slot.toLowerCase()}`,
                  );
                  return (
                    <div key={slot} className="space-y-1">
                      <p className="text-xs font-medium text-on-muted">
                        {slotLabel}
                      </p>
                      <MealPlanCell
                        date={dateStr}
                        slot={slot}
                        slotLabel={slotLabel}
                        entries={
                          entriesBySlotAndDate.get(`${dateStr}::${slot}`) ?? []
                        }
                        isPast={isPast}
                        canWrite={canWrite}
                        onAdd={onAddEntry}
                        onRemove={onRemoveEntry}
                        onCook={onCookEntry}
                        t={t}
                      />
                    </div>
                  );
                })}
              </section>
            );
          })}
        </div>
      </DndContext>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      onDragEnd={handleDragEnd}
      accessibility={dndA11y}
    >
      {/* The grid is at least 600px wide and 14 days push it past 1400, so it
          scrolls inside itself on narrow screens. Without a cue that reads as
          "there is more this way", a phone shows four days and looks complete —
          hence the fade on the trailing edge (only while there is more to
          scroll to), and the shadow that keeps the sticky label column from
          having cells slide underneath it unannounced. The grid's own
          padding gives the filled cells' -m-0.5 room: without it
          the last column ran 2px past the track and made the grid scroll. */}
      <MealPlanScroller>
        <div
          className="grid gap-1.5 min-w-[600px] p-0.5"
          style={{
            gridTemplateColumns: `80px repeat(${days.length}, minmax(100px, 1fr))`,
          }}
        >
          <div className="sticky left-0 z-10 bg-surface shadow-[1px_0_0_0_rgb(var(--border-default))]" />
          {days.map((day) => (
            <div key={day.toISOString()} className="text-center pb-1">
              <p className="text-xs font-medium text-on-muted">
                {format(day, "EEE", { locale: dateFnsLocale() })}
              </p>
              <p className="text-sm font-semibold">
                {format(day, "d MMM", { locale: dateFnsLocale() })}
              </p>
            </div>
          ))}

          {activeSlots.map((slot) => {
            const slotLabel = t(`meal_planner.slots.${slot.toLowerCase()}`);
            return (
              <Fragment key={slot}>
                <div className="sticky left-0 z-10 bg-surface shadow-[1px_0_0_0_rgb(var(--border-default))] flex items-center justify-end pr-2">
                  <span className="text-xs font-medium text-on-muted">
                    {slotLabel}
                  </span>
                </div>
                {days.map((day) => {
                  const dateStr = format(day, "yyyy-MM-dd");
                  const entries =
                    entriesBySlotAndDate.get(`${dateStr}::${slot}`) ?? [];
                  const isPast = isBefore(day, today);
                  return (
                    <MealPlanCell
                      key={`${dateStr}-${slot}`}
                      date={dateStr}
                      slot={slot}
                      slotLabel={slotLabel}
                      entries={entries}
                      isPast={isPast}
                      canWrite={canWrite}
                      onAdd={onAddEntry}
                      onRemove={onRemoveEntry}
                      onCook={onCookEntry}
                      t={t}
                    />
                  );
                })}
              </Fragment>
            );
          })}
        </div>
      </MealPlanScroller>
    </DndContext>
  );
}
