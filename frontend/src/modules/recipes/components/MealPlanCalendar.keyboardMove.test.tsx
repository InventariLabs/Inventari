/**
 * A keyboard move remounts the entry card inside its new cell, so the node the
 * reader was standing on is gone by the time the drop lands and focus falls to
 * the body — measured on the running app at 1440 and at 390: after moving an
 * entry to another day, `document.activeElement` was `BODY`, while a drop in
 * the same cell left focus on the grip. The reader lost their place and tabbed
 * from the top of the page again.
 *
 * These tests drive the calendar's own `onDragEnd` — captured from the real
 * DndContext — and then re-render with the moved plan, which is what the
 * optimistic cache update does. Both paths are pinned: a move to another cell
 * puts focus back on the entry that moved, and a drop that moves nothing
 * leaves focus exactly where the reader had it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { DragEndEvent } from "@dnd-kit/core";
import type { ReactNode } from "react";

import type {
  MealPlan,
  MealPlanEntry,
} from "@/modules/recipes/types/mealplans";
import { tFor } from "@/test/mocks/i18n";

const dragEnds: ((event: DragEndEvent) => void)[] = [];

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...actual,
    DndContext: (props: {
      children?: ReactNode;
      onDragEnd?: (event: DragEndEvent) => void;
    }) => {
      if (props.onDragEnd) dragEnds.push(props.onDragEnd);
      return <actual.DndContext {...props} />;
    },
  };
});

import { MealPlanCalendar } from "./MealPlanCalendar";

// A Monday and the day after — in the future, so no cell is locked and every
// entry still offers its grip.
const PLAN_START = "2027-01-04";
const PLAN_END = "2027-01-05";

function entry(id: string, date: string): MealPlanEntry {
  return {
    id,
    date,
    slot: "LUNCH",
    recipe_id: "r1",
    recipe_name: `Danie ${id}`,
    recipe_image_url: null,
    servings: 2,
    notes: null,
    order: 0,
    is_completed: false,
    picking_session_id: null,
  };
}

function planWith(entries: MealPlanEntry[]): MealPlan {
  return {
    id: "mp1",
    name: null,
    start_date: PLAN_START,
    end_date: PLAN_END,
    enabled_slots: ["LUNCH"],
    default_servings: 2,
    shopping_list_id: null,
    meals_added_since_list: false,
    notes: null,
    entries,
    daily_nutrition_summary: [],
    created_by: "u1",
    created_at: "2027-01-04T08:00:00Z",
    updated_at: "2027-01-04T08:00:00Z",
  };
}

function renderCalendar(plan: MealPlan, onMoveEntry = vi.fn()) {
  const view = render(
    <MealPlanCalendar
      plan={plan}
      onAddEntry={vi.fn()}
      onRemoveEntry={vi.fn()}
      onCookEntry={vi.fn()}
      onMoveEntry={onMoveEntry}
      t={tFor("recipes")}
    />,
  );
  const dropOn = (entryId: string, date: string) => {
    const handler = dragEnds[dragEnds.length - 1];
    if (!handler) throw new Error("the calendar rendered no drag context");
    act(() => {
      handler({
        active: { id: entryId },
        over: {
          data: {
            current: {
              type: "meal-plan-cell",
              date,
              slot: "LUNCH",
              isPast: false,
            },
          },
        },
      } as unknown as DragEndEvent);
    });
  };
  return { ...view, onMoveEntry, dropOn };
}

beforeEach(() => {
  dragEnds.length = 0;
});

describe("MealPlanCalendar keeps the keyboard's place when an entry moves", () => {
  it("leaves focus on the entry it moved into another cell", async () => {
    const { rerender, dropOn } = renderCalendar(
      planWith([entry("e1", PLAN_START)]),
    );
    const [grip] = await screen.findAllByRole("button", {
      name: /^Drag to move/,
    });
    grip.focus();
    expect(document.activeElement).toBe(grip);

    dropOn("e1", PLAN_END);
    // The move is optimistic: the card is drawn in its new cell right away.
    // (onMoveEntry is the caller's; the cache update behind it is the parent's.)
    rerender(
      <MealPlanCalendar
        plan={planWith([entry("e1", PLAN_END)])}
        onAddEntry={vi.fn()}
        onRemoveEntry={vi.fn()}
        onCookEntry={vi.fn()}
        onMoveEntry={vi.fn()}
        t={tFor("recipes")}
      />,
    );

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: /^Drag to move/ }),
      ),
    );
    expect(document.activeElement).not.toBe(document.body);
  });

  it("leaves focus alone when the drop moves nothing", async () => {
    const first = entry("e1", PLAN_START);
    const second = entry("e2", PLAN_START);
    const { dropOn } = renderCalendar(planWith([first, second]));
    const grips = await screen.findAllByRole("button", {
      name: /^Drag to move/,
    });
    // The reader stands on the second entry and drops the first one back into
    // the cell it came from: nothing remounts, so nothing may steal the focus.
    grips[1].focus();
    expect(document.activeElement).toBe(grips[1]);

    dropOn("e1", PLAN_START);

    await waitFor(() => expect(document.activeElement).toBe(grips[1]));
  });
});
