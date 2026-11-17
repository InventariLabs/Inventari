import {
  addDays,
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  format,
  startOfMonth,
  startOfWeek,
} from "date-fns";

export type PlanView = "week" | "month";

export interface PlanPeriod {
  from: string;
  to: string;
  days: string[];
  /** Blank cells before the first day of a month, so weeks line up Monday-first. */
  leading: number;
}

const iso = (day: Date) => format(day, "yyyy-MM-dd");

/** The days a plan view shows around *anchor*: its week, or its calendar month. */
export function planPeriod(view: PlanView, anchor: Date): PlanPeriod {
  const first =
    view === "week"
      ? startOfWeek(anchor, { weekStartsOn: 1 })
      : startOfMonth(anchor);
  const last = view === "week" ? addDays(first, 6) : endOfMonth(anchor);
  const days = eachDayOfInterval({ start: first, end: last }).map(iso);
  const leading =
    view === "month" ? (first.getDay() + 6) % 7 : 0; /* Monday-first */
  return { from: iso(first), to: iso(last), days, leading };
}

/** The anchor one step earlier or later: a week, or a month. */
export function shiftAnchor(view: PlanView, anchor: Date, step: -1 | 1): Date {
  return view === "week" ? addWeeks(anchor, step) : addMonths(anchor, step);
}
