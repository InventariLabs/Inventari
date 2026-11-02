import { describe, expect, it } from "vitest";
import type { WorkItem } from "@/modules/warehouse/types";
import {
  ALL_PEOPLE,
  NOBODY,
  assigneeParam,
  startOfDayIso,
  progressPercent,
  splitDuration,
} from "./boardColumns";

const NOW = new Date(2026, 9, 21, 15, 0, 0);

function card(over: Partial<WorkItem>): WorkItem {
  return {
    key: "k",
    kind: "ship",
    state: "todo",
    source_kind: "document",
    source_id: "s",
    overdue: false,
    ...over,
  } as WorkItem;
}

describe("assigneeParam", () => {
  it("asks the server for everybody, nobody or one person", () => {
    expect(assigneeParam(ALL_PEOPLE)).toBeUndefined();
    expect(assigneeParam(NOBODY)).toBe("none");
    expect(assigneeParam("u1")).toBe("u1");
  });
});

describe("startOfDayIso", () => {
  it("is midnight of the reader's own day, not 24 hours ago", () => {
    const start = new Date(startOfDayIso(NOW));

    expect(start.getTime()).toBe(new Date(2026, 9, 21).getTime());
  });
});

describe("progressPercent", () => {
  it("is the finished share of the lines of a card under way", () => {
    expect(
      progressPercent(
        card({ state: "in_progress", count: "3", lines_done: 2 }),
      ),
    ).toBe(67);
  });

  it("is absent before work starts, after it ends, or without lines", () => {
    expect(
      progressPercent(card({ state: "todo", count: "3", lines_done: 0 })),
    ).toBeNull();
    expect(
      progressPercent(
        card({ state: "in_progress", count: "0", lines_done: 0 }),
      ),
    ).toBeNull();
    expect(progressPercent(card({ state: "in_progress" }))).toBeNull();
  });
});

describe("splitDuration", () => {
  it("rounds to whole minutes", () => {
    expect(splitDuration(9600)).toEqual({ hours: 2, minutes: 40 });
    expect(splitDuration(89)).toEqual({ hours: 0, minutes: 1 });
  });
});
