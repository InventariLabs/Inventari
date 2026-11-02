/**
 * The meal plan calendar is drag-into-target: entries are `useDraggable`,
 * cells are `useDroppable`, and nothing on the screen is sortable. Passing
 * `sortable: true` to the shared sensors hands the keyboard
 * `sortableKeyboardCoordinates`, which resolves the lifted element against
 * the containers registered in a SortableContext — and with none here the
 * getter answers `undefined`, so the space bar lifted an entry, the arrows
 * never moved it, and the screen-reader instruction ("press the space bar,
 * move with the arrows") was a promise the screen did not keep.
 *
 * A drag-into-target context keeps the library's default coordinates (the
 * rule is documented on `useDndSensors`). These tests read the sensors prop
 * each of the calendar's two DndContexts actually receives, at both widths,
 * so a return to sortable coordinates fails here before it fails a reader.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import {
  KeyboardSensor,
  PointerSensor,
  type SensorDescriptor,
  type SensorOptions,
} from "@dnd-kit/core";

import type { MealPlan } from "@/modules/recipes/types/mealplans";
import { tFor, withLanguage } from "@/test/mocks/i18n";

const sensorsSeen: SensorDescriptor<SensorOptions>[][] = [];

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...actual,
    DndContext: (props: {
      children?: ReactNode;
      sensors?: SensorDescriptor<SensorOptions>[];
    }) => {
      sensorsSeen.push(props.sensors ?? []);
      return <>{props.children}</>;
    },
  };
});

import { MealPlanCalendar } from "./MealPlanCalendar";

function mealPlan(): MealPlan {
  return {
    id: "mp1",
    name: null,
    start_date: "2026-08-14",
    end_date: "2026-08-15",
    enabled_slots: ["BREAKFAST", "LUNCH", "DINNER"],
    default_servings: 2,
    shopping_list_id: null,
    meals_added_since_list: false,
    notes: null,
    entries: [],
    daily_nutrition_summary: [],
    created_by: "u1",
    created_at: "2026-08-14T08:00:00Z",
    updated_at: "2026-08-14T08:00:00Z",
  };
}

function renderCalendar() {
  const noop = vi.fn();
  return render(
    <MealPlanCalendar
      plan={mealPlan()}
      onAddEntry={noop}
      onRemoveEntry={noop}
      onCookEntry={noop}
      onMoveEntry={noop}
      t={tFor("recipes")}
    />,
  );
}

function expectDefaultKeyboardCoordinates(
  sensors: SensorDescriptor<SensorOptions>[],
) {
  const kinds = sensors.map((d) => d.sensor);
  expect(kinds, "the pointer stays a sensor of the calendar").toContain(
    PointerSensor,
  );
  expect(
    kinds,
    "the instruction promises space and arrows, so the keyboard stays a sensor",
  ).toContain(KeyboardSensor);

  const keyboard = sensors.find((d) => d.sensor === KeyboardSensor);
  const getter = (
    keyboard?.options as { coordinateGetter?: unknown } | undefined
  )?.coordinateGetter;
  expect(
    getter,
    "nothing on this screen is sortable: sortable coordinates resolve against " +
      "a SortableContext that does not exist here and the arrows never move " +
      "the lifted entry — a drag-into-target context keeps the library's " +
      "default coordinates",
  ).toBeUndefined();
}

describe("MealPlanCalendar keyboard sensors", () => {
  beforeEach(() => {
    sensorsSeen.length = 0;
  });

  function expectEveryRenderDefaultCoordinates() {
    // A re-render re-hands the props, so the mock sees the same sensors more
    // than once — every hand-over is asserted, not only the first.
    expect(
      sensorsSeen.length,
      "the calendar rendered no drag context at all",
    ).toBeGreaterThan(0);
    for (const sensors of sensorsSeen) {
      expectDefaultKeyboardCoordinates(sensors);
    }
  }

  it("gives the wide grid the library's default keyboard coordinates", async () => {
    await withLanguage("en", () => {
      renderCalendar();
    });
    expectEveryRenderDefaultCoordinates();
  });

  describe("on a phone", () => {
    const originalMatchMedia = window.matchMedia;

    beforeEach(() => {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: query.includes("max-width"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }));
    });

    afterEach(() => {
      window.matchMedia = originalMatchMedia;
    });

    it("gives the narrow layout the same default keyboard coordinates", async () => {
      await withLanguage("en", () => {
        renderCalendar();
      });
      expectEveryRenderDefaultCoordinates();
    });
  });
});
