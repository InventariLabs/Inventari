/**
 * Turning a wall-clock pair (a day and a time) into the instant the server
 * stores, and back, in the organization's timezone.
 *
 * The date field is a day (`yyyy-MM-dd`) and the time field is `HH:mm`; the
 * window is stored as an instant, so the two are read on the organization's
 * clock — the same clock the "today" view and the overdue rule use.
 */

import { instantToZonedWall, zonedWallTimeToInstant } from "@/module-sdk";

/** `2026-12-01` + `09:00` on the organization's clock → an ISO instant. */
export function wallTimeToIso(
  date: string,
  time: string,
  timeZone?: string,
): string {
  return zonedWallTimeToInstant(date, time, timeZone).toISOString();
}

/** An ISO instant → `{ date: 'yyyy-MM-dd', time: 'HH:mm' }` on that clock. */
export function isoToWall(
  iso: string,
  timeZone?: string,
): { date: string; time: string } {
  return instantToZonedWall(iso, timeZone);
}

/** The date of an instant on the wall clock, as `yyyy-MM-dd`. */
export function isoDate(iso: string, timeZone?: string): string {
  return isoToWall(iso, timeZone).date;
}

/** Add days to a `yyyy-MM-dd` value. */
export function addDays(date: string, days: number): string {
  const [year, month, day] = date.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + days));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${next.getUTCFullYear()}-${pad(next.getUTCMonth() + 1)}-${pad(next.getUTCDate())}`;
}

/** Monday of the week *date* falls in, as `yyyy-MM-dd`. */
export function startOfWeek(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const value = new Date(Date.UTC(year, month - 1, day));
  const weekday = (value.getUTCDay() + 6) % 7;
  return addDays(date, -weekday);
}

export function daysBetween(start: string, count: number): string[] {
  return Array.from({ length: count }, (_, index) => addDays(start, index));
}
