/**
 * The instant a form sends for a picked day.
 *
 * The backend reads arrivals through the organization's clock and pins
 * wall-clock endings in it (create_campaign in equipment). A day that
 * arrives as an instant in the *browser's* zone therefore lands on the
 * org's next day whenever the organization is east of the reader — the
 * write-side mirror of the read bug fixed in the formatters: a Warsaw admin picking "Sep 30" for a Tokyo organization
 * stored October 1st, and every screen but the form said so.
 *
 * Noon, not 23:59:59: a mid-day wall clock survives every DST shift
 * (transitions happen at night), and the backend re-pins the arrival to
 * the true end of the day it reads — the form only owes an instant that
 * falls *inside* the org's day.
 */

function zoneOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);
  const byType: Record<string, string> = {};
  for (const part of parts) {
    byType[part.type] = part.value;
  }
  const asUTC = Date.UTC(
    Number(byType.year),
    Number(byType.month) - 1,
    Number(byType.day),
    Number(byType.hour) % 24,
    Number(byType.minute),
    Number(byType.second),
  );
  return asUTC - instant.getTime();
}

export function instantInsideDay(
  dayIso: string,
  timeZone: string | undefined,
): Date {
  const [year, month, day] = dayIso.split("-").map(Number);
  if (timeZone === undefined) {
    // Org zone unknown (still loading): the browser's day — the shape the
    // form sent before the org clock existed. The read side falls back the
    // same way, and the backend still pins the end of the day it reads.
    return new Date(year, month - 1, day, 12, 0, 0);
  }
  const naive = Date.UTC(year, month - 1, day, 12, 0, 0);
  const offset = zoneOffsetMs(new Date(naive), timeZone);
  const instant = new Date(naive - offset);
  // The first guess can land on the far side of a DST edge; correct once
  // against the offset the corrected instant actually sees.
  const corrected = zoneOffsetMs(instant, timeZone);
  return corrected === offset ? instant : new Date(naive - corrected);
}

/**
 * Today's date on the given zone's calendar, `YYYY-MM-DD`.
 *
 * The picker's floor is the org's today, not the reader's: a calendar that
 * floors on the reader's clock offers a day the organization has already
 * finished (a Los Angeles reader managing an Auckland org was offered
 * "yesterday"). `Intl` with an undefined zone resolves to the browser's,
 * which is the same fallback the rest of this module speaks.
 */
export function todayInZone(timeZone: string | undefined): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
