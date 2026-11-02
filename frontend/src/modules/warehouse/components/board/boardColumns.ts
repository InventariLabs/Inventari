import type { WorkItem } from "@/modules/warehouse/types";

/** The board's columns, left to right: the work item states themselves. */
export const COLUMN_STATES = ["todo", "in_progress", "done"] as const;
export type ColumnState = (typeof COLUMN_STATES)[number];

/** Whose cards to show: everybody's, nobody's, or one person's. */
export type PersonFilter = "all" | "none" | string;

export const ALL_PEOPLE = "all";
export const NOBODY = "none";

/** What the server's `assignee` filter calls a person's choice on the chips:
 * nothing for everybody, `none` for the cards nobody has, else the user id. */
export function assigneeParam(person: PersonFilter): string | undefined {
  return person === ALL_PEOPLE
    ? undefined
    : person === NOBODY
      ? "none"
      : person;
}

/** The start of the reader's calendar day, which is where "Done today" begins;
 * the server cannot know the reader's time zone, so the browser says it. */
export function startOfDayIso(now: Date): string {
  return new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).toISOString();
}

/** How far a card under way has got, as a percentage; `null` where the card
 * has no lines to count. */
export function progressPercent(item: WorkItem): number | null {
  const total = Number(item.count ?? 0);
  if (item.state !== "in_progress" || item.lines_done == null || total <= 0) {
    return null;
  }
  return Math.min(100, Math.round((item.lines_done / total) * 100));
}

/** A span of seconds as whole hours and minutes. */
export function splitDuration(seconds: number): {
  hours: number;
  minutes: number;
} {
  const totalMinutes = Math.round(seconds / 60);
  return { hours: Math.floor(totalMinutes / 60), minutes: totalMinutes % 60 };
}
