/**
 * Formatting utilities — dates, money, byte sizes.
 *
 * The date subsystem lives here rather than in `helpers.ts` (dedup 6.4): the
 * caches, `renderDate` and the six public formatters are one unit, and this
 * file is where a reader looks for them. `helpers.ts` re-exports them so the
 * many existing `from "@/utils/helpers"` imports keep working; the dependency
 * runs one way only, helpers → formatters, so there is no import cycle.
 */
import { enGB, enUS, pl, de, fr, es } from "date-fns/locale";
import type { Locale } from "date-fns";
import i18next from "i18next";
import { QUANTITY_STEP } from "@/hooks/useUomPrecision";

/**
 * Formats a date string to DD.MM.YYYY format.
 */
type FormatDateFn = (key: string, options?: Record<string, unknown>) => string;

export type DateVariant =
  "date" | "datetime" | "datetime-seconds" | "time" | "medium";

const dateFormatterCache = new Map<string, Intl.DateTimeFormat>();

let organizationCountry: string | null = null;

/**
 * Tells the formatters which country the organization is in, so English
 * speaks its regional variant. Called where the organization is loaded
 * (`useOrganization`); `null` or an empty value means "not set".
 */
export function setOrganizationCountry(country: string | null | undefined) {
  organizationCountry = country ? country.trim().toUpperCase() || null : null;
}

/**
 * The locale every formatter hands to `Intl`: the interface language, with
 * English narrowed to a region by the organization's country alone (the US
 * keeps `en-US`, any other country gets `en-GB`, no country stays `en-US`).
 * "en" alone is the American spelling to `Intl`, so a British reader saw
 * 03/04/2026 for 3 April. The country is the one input the backend also has
 * when it prints a document (`format_date_for`), so a screen and its
 * printout never disagree; the browser's region and a regional tag on the
 * interface language are deliberately not read, because a printout could not
 * follow them.
 */
export function formatLocale(): string {
  const language = i18next.language || "en";
  if (language.split("-")[0] !== "en") return language;
  return organizationCountry && organizationCountry !== "US"
    ? "en-GB"
    : "en-US";
}

/**
 * Cheap zone signature for the formatter cache: the offset changes exactly
 * when the effective zone changes, and two zones sharing an offset share
 * the formatter without changing any output. Without the offset in the key
 * a formatter built under one zone kept serving another after the zone
 * changed under it.
 */
function zoneSignature(): number {
  return new Date().getTimezoneOffset();
}

function getDateFormatter(
  locale: string,
  variant: DateVariant,
  timeZone?: string,
): Intl.DateTimeFormat {
  // A named zone never collides with the numeric reader-zone signature, and
  // two org-clock renders in one zone share a formatter the same way two
  // reader-zone renders do.
  const key = `${locale}::${variant}::${timeZone ?? zoneSignature()}`;
  let formatter = dateFormatterCache.get(key);
  if (!formatter) {
    // English never prints a numeric day-month pair: 04/11/2026 is April 11
    // to a US reader and 4 November to everyone else, so it spells the month.
    const day: Intl.DateTimeFormatOptions = locale.startsWith("en")
      ? { day: "numeric", month: "short", year: "numeric" }
      : { day: "2-digit", month: "2-digit", year: "numeric" };
    const hm: Intl.DateTimeFormatOptions = {
      hour: "2-digit",
      minute: "2-digit",
    };
    const opts: Intl.DateTimeFormatOptions =
      variant === "time"
        ? hm
        : variant === "datetime"
          ? { ...day, ...hm }
          : variant === "datetime-seconds"
            ? { ...day, ...hm, second: "2-digit" }
            : variant === "medium"
              ? { day: "numeric", month: "short", year: "numeric" }
              : day;
    formatter = new Intl.DateTimeFormat(
      locale,
      timeZone ? { ...opts, timeZone } : opts,
    );
    dateFormatterCache.set(key, formatter);
  }
  return formatter;
}

function renderDate(
  dateString: string | null | undefined,
  variant: DateVariant,
  fallback: string,
  timeZone?: string,
): string {
  if (!dateString) return fallback;
  const date = parseDateValue(dateString);
  if (isNaN(date.getTime())) return fallback;
  return getDateFormatter(formatLocale(), variant, timeZone).format(date);
}

/**
 * Format a value the backend pinned to the *organization's* clock.
 *
 * Three families of dates exist in this app, and they owe the reader
 * different clocks:
 *
 * 1. **Calendar days** — date-only strings ("2026-09-06", a SQL DATE or an
 *    expiry printed on a carton). Zone-free: the written day is the shown
 *    day, via `parseDateValue`'s local-midnight read. Never pass one of
 *    these here; `formatDate` already renders them correctly for everyone.
 * 2. **Reader moments** — instants whose "when" belongs to the reader's own
 *    experience (created_at, launched_at, audit trail, delivery logs).
 *    Render with `formatDate`, in the browser's zone.
 * 3. **Org-clock days** — instants the backend pinned to the organization's
 *    calendar before storing (an attestation deadline is the end of its own
 *    day in the org's zone, read as "last day to answer", never a time).
 *    The browser's zone knows nothing about that pin: a reader east of the
 *    organization saw the next day. Render these through this function with
 *    the organization's zone so every device reads the day the org meant.
 *    `useFormatOrgDay` is the one place that knows the zone.
 *
 * The entry path is part of the same contract: a day picked in a form
 * travels as an instant *inside* the organization's day (`instantInsideDay`),
 * because the backend reads arrivals through the org clock. A browser-zone
 * arrival stored the next day for every organization east of the reader —
 * the write-side mirror of the read bug this zone path fixes.
 *
 * Known consequence, kept deliberately: the stored value is an
 * instant, so the day a saved record shows follows the organization's
 * *current* zone — moving the org's timezone re-dates saved deadlines on
 * screen. The alternative is storing the
 * calendar day itself.
 */
export const formatDateInZone = (
  dateString: string | null | undefined,
  timeZone: string | undefined,
  // Date-only values keep the calendar-day path even when a zone is known:
  // their day is already correct for every reader, and routing a local
  // midnight through a foreign zone would move it.
  { variant = "date" }: { variant?: DateVariant } = {},
): string => {
  if (dateString && /^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    return renderDate(dateString, variant, renderEmpty());
  }
  return renderDate(dateString, variant, renderEmpty(), timeZone);
};

/**
 * Parse a serialized date into the `Date` its writer meant.
 *
 * A value without a time part ("2026-09-06" — what a SQL DATE column
 * serializes to) is a calendar day, not a moment on the timeline.
 * `new Date("2026-09-06")` reads it as UTC midnight, so a reader west of
 * UTC saw the previous day than the one written. Such values are built as
 * local midnight instead: the day that was written is the day that is
 * shown, whatever zone the reader is in.
 */
function parseDateValue(dateString: string): Date {
  const calendarDay = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateString);
  if (calendarDay) {
    return new Date(
      Number(calendarDay[1]),
      Number(calendarDay[2]) - 1,
      Number(calendarDay[3]),
    );
  }
  return new Date(dateString);
}

/**
 * Resolve the placeholder shown when a date is missing/invalid.
 *
 * Reads the current i18n language and returns a locale-appropriate
 * dash (—, –, –, depending on locale). Falls back to ASCII "-" when
 * the locale has no translation available so we never end up
 * showing the i18next debug "key 'empty (en)'" string in the UI.
 */
function renderEmpty(): string {
  // No t() here — we deliberately avoid depending on i18next so this
  // helper is safe to call from places that haven't loaded the
  // t() function yet. The Unicode em dash is locale-neutral and
  // renders identically across en/pl/de/fr/es.
  return "\u2014";
}

export const formatDate = (
  dateString: string | null | undefined,
  // Legacy second argument kept for source-level back-compat with
  // callers that still pass `t`. Unused now that we resolve the
  // empty placeholder ourselves.
  _t?: FormatDateFn,
): string => renderDate(dateString, "date", renderEmpty());

/**
 * Locale-aware "medium" date: "Jul 24, 2026" (en), "24 lip 2026" (pl).
 */
export const formatDateMedium = (
  dateString: string | null | undefined,
): string => renderDate(dateString, "medium", renderEmpty());

/**
 * Locale-aware compact date range: "24–30 Jul 2026" when both dates
 * fall in the same month, "24 Jul – 2 Aug 2026" when only the year
 * matches, otherwise two full medium dates.
 */
export function formatDateRange(
  startString: string | null | undefined,
  endString: string | null | undefined,
): string {
  if (!startString || !endString) return renderEmpty();
  const start = parseDateValue(startString);
  const end = parseDateValue(endString);
  if (isNaN(start.getTime()) || isNaN(end.getTime())) return renderEmpty();
  const locale = formatLocale();
  const parts = (d: Date) =>
    Object.fromEntries(
      new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
        .formatToParts(d)
        .filter((p) => p.type !== "literal")
        .map((p) => [p.type, p.value]),
    );
  const s = parts(start);
  const e = parts(end);
  const dash = "\u2013";
  if (s.year === e.year && s.month === e.month)
    return `${s.day}${dash}${e.day} ${e.month} ${e.year}`;
  if (s.year === e.year)
    return `${s.day} ${s.month} ${dash} ${e.day} ${e.month} ${e.year}`;
  return `${s.day} ${s.month} ${s.year} ${dash} ${e.day} ${e.month} ${e.year}`;
}

export const formatDateTime = (
  dateString: string | null | undefined,
  _t?: FormatDateFn,
): string => renderDate(dateString, "datetime", renderEmpty());

/**
 * Same as `formatDateTime`, with seconds — for logs where several rows land
 * inside one minute and the order between them is the point. Four webhook
 * retries all read "20.08.2026, 20:34" without it.
 */
export const formatDateTimePrecise = (
  dateString: string | null | undefined,
): string => renderDate(dateString, "datetime-seconds", renderEmpty());

export const formatTime = (
  dateString: string | null | undefined,
  _t?: FormatDateFn,
): string => renderDate(dateString, "time", renderEmpty());

/**
 * When something in a journal happened: the clock time if it was earlier
 * on the reader's today, the date otherwise. Built from `formatTime` and
 * `formatDate` rather than a relative phrase of its own, so a journal row
 * cannot spell a day differently from every other screen.
 */
export function formatRecentMoment(
  dateString: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!dateString) return renderEmpty();
  const at = parseDateValue(dateString);
  if (isNaN(at.getTime())) return renderEmpty();
  const sameDay =
    at.getFullYear() === now.getFullYear() &&
    at.getMonth() === now.getMonth() &&
    at.getDate() === now.getDate();
  return sameDay ? formatTime(dateString) : formatDate(dateString);
}

const monthFormatterCache = new Map<string, Intl.DateTimeFormat>();

/**
 * Locale-aware long month name for a (year, month) pair — used by
 * period pickers that don't have a full date to render.
 * `month` is 1-based (1 = January).
 */
export function formatMonthName(year: number, month: number): string {
  if (!Number.isInteger(month) || month < 1 || month > 12) return renderEmpty();
  const locale = formatLocale();
  let formatter = monthFormatterCache.get(`${locale}::${zoneSignature()}`);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, { month: "long" });
    monthFormatterCache.set(`${locale}::${zoneSignature()}`, formatter);
  }
  return formatter.format(new Date(year, month - 1, 1));
}

const DATE_FNS_LOCALES: Record<string, Locale> = {
  en: enUS,
  pl,
  de,
  fr,
  es,
};

/**
 * The date-fns Locale matching the current i18n language, so weekday and
 * month names ("Fri 14 Aug") follow the interface language, and English its
 * region (`formatLocale`).
 * Falls back to enUS for unknown languages.
 */
export function dateFnsLocale(): Locale {
  const lang = (i18next.language || "en").split("-")[0];
  if (lang === "en") return formatLocale() === "en-US" ? enUS : enGB;
  return DATE_FNS_LOCALES[lang] ?? enUS;
}

/**
 * An amount written the way the reader's language writes money.
 *
 * `locale` defaults to the interface language rather than to English. The
 * old default was `"en"`, and a call site that forgot the third argument
 * therefore rendered "PLN 1,234.56" on a Polish screen — a mistake that
 * looked like a formatting bug rather than the missing argument it was, and
 * that ten of the eleven calls in one module got right while the eleventh
 * did not. Prefer `useMoney`, which supplies both the currency and the
 * locale; this default is the floor, not the recommendation.
 */
/**
 * A quantity or amount off the wire, as a number to compute with.
 *
 * The API sends these as strings, exact: a Decimal is not rounded into a
 * double on the way out. Anything that has to add, compare or subtract one
 * converts here rather than at each call site — and gets `null` back for a
 * value that was absent or is not a number, so "no answer" never turns into
 * a confident zero.
 */
export function toAmount(
  value: string | number | null | undefined,
): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(
  amount: number | string | null | undefined,
  currency?: string | null,
  locale?: string,
): string {
  if (amount == null || amount === "") return "\u2014";
  const n = typeof amount === "string" ? parseFloat(amount) : amount;
  if (!Number.isFinite(n)) return "\u2014";
  const resolvedLocale = locale ?? i18next.language ?? "en";
  try {
    if (currency) {
      return new Intl.NumberFormat(resolvedLocale, {
        style: "currency",
        currency,
        currencyDisplay: "symbol",
      }).format(n);
    }
    // a bare number is a silent lie — without a currency show an
    // explicit question mark instead of pretending the amount is complete.
    return `${new Intl.NumberFormat(resolvedLocale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n)} ?`;
  } catch {
    const fallback = n.toFixed(2);
    return currency ? `${fallback} ${currency}` : `${fallback} ?`;
  }
}

/**
 * Today as `yyyy-MM-dd` in the user's own timezone.
 *
 * `toISOString()` answers in UTC, so between midnight and the offset it
 * returns yesterday — which prefilled maintenance and checkout dates a day
 * early for anyone east of Greenwich, and dated their exports the same way.
 */
export function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Today's date for an export filename — see {@link todayIso}. */
export function getTodayFilename(): string {
  return todayIso();
}

/**
 * Human-readable file size: `B` under 1 KiB, `KB` under 1 MiB, `MB` above.
 *
 * Moved out of `equipment/AssetAttachmentsSection` so a second caller does not
 * have to reinvent the thresholds. Note `utils/fileValidation.ts` is *not* a
 * caller: it renders a fixed limit ("Maximum size: 10 MB") and always wants MB,
 * with no unit selection.
 *
 * The size is a number the reader reads, so the figure takes the reader's
 * decimal mark — "1,5 MB" on a Polish screen.
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${formatNumberLocale(bytes / 1024, 1)} KB`;
  return `${formatNumberLocale(bytes / (1024 * 1024), 1)} MB`;
}

/**
 * Display symbol for a currency code ("EUR" → "€", "USD" → "$",
 * "PLN" → "zł" in a Polish locale) derived from `Intl.NumberFormat`
 * instead of a hand-maintained symbol map. Falls back to the raw
 * currency code when the runtime cannot format it, and to an empty
 * string when no currency is given.
 */
export function currencySymbol(
  currency: string | null | undefined,
  locale?: string,
): string {
  if (!currency) return "";
  const resolvedLocale = locale ?? i18next.language ?? "en";
  try {
    const parts = new Intl.NumberFormat(resolvedLocale, {
      style: "currency",
      currency,
      currencyDisplay: "symbol",
    }).formatToParts(0);
    return parts.find((p) => p.type === "currency")?.value ?? currency;
  } catch {
    return currency;
  }
}

/** The unit's step with the column's padding stripped: "0.001000" is 0.001. */
export function stepText(
  rounding: string | number | null | undefined,
): string | null {
  if (rounding == null || rounding === "") return null;
  const text = String(rounding).trim();
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  return text.includes(".") ? text.replace(/\.?0+$/, "") || "0" : text;
}

/**
 * Decimal places the unit leaves — three for a kilogram, none for a piece.
 *
 * Counted off the step as it is written, not off the column it is stored in:
 * `numeric(12,6)` serializes a thousandth as "0.001000", and a rule read off
 * that column would be a rule nobody has. One function for both directions —
 * the counting box refuses a fourth decimal on a gram because of it, and the
 * screens below print the same number of places for the same reason.
 */
export function decimalsAllowedBy(
  rounding: string | number | null | undefined,
): number {
  const step = stepText(rounding);
  if (step === null || !step.includes(".")) return 0;
  return step.length - step.indexOf(".") - 1;
}

/**
 * The number a reader should see for a quantity, in their own language.
 *
 * Two things go wrong when the string off the wire is printed as it came.
 * `Item.quantity` is `numeric(10,3)` and every value is quantized to three
 * places on the way in, so a piece arrives as "1.000" — three decimals on a
 * unit that has none, saying a piece divides. And the padding is written the
 * database's way, so a Polish screen showed "1.000 szt." beside "0,00 PLN".
 *
 * With `rounding` the unit's step widens the places, but never below the
 * three the quantity columns store: the step says how finely an amount is
 * typed, not what a record holds. A pack of rice cooked down by 100 g is 0.9
 * pack, and cutting to the step printed "1 pack" on the Products list while
 * Stock, Movements and the totals said 0.9. Without it, the value is shown
 * as precisely as it arrived with the padding stripped — no precision is
 * invented for a record whose unit nobody recorded.
 *
 * Thousands are grouped the way the reader's language groups them — "12 345,6"
 * in Polish, "12,345.6" in English — on every screen, production included, and
 * `formatQuantityLocale` below writes them the same way. There were two
 * answers to that question once, one per formatter, and the same stock read
 * "12 345,6" on one screen and "12345,6" on the next. The value is for
 * reading only: nothing hands it back to an input or a file.
 */
export function formatQuantityValue(
  value: number | string | null | undefined,
  rounding?: string | number | null,
  locale?: string,
): string {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;

  const trimmed = formatDecimalQty(text);
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return trimmed;
  const decimals =
    rounding == null
      ? (trimmed.split(".")[1]?.length ?? 0)
      : Math.max(decimalsAllowedBy(rounding), decimalsAllowedBy(QUANTITY_STEP));
  try {
    return new Intl.NumberFormat(locale ?? i18next.language ?? "en", {
      maximumFractionDigits: decimals,
    }).format(n);
  } catch {
    return trimmed;
  }
}

/**
 * A quantity with its unit — or bare, when the product has no unit recorded.
 *
 * The UI used to append "pcs" wherever a unit was missing, which showed the
 * user a unit that is not in the data. 500 g of something then read as 500
 * pieces.
 */
export function formatQuantity(
  quantity: number | string | null | undefined,
  unitSymbol?: string | null,
  rounding?: string | number | null,
): string {
  if (quantity === null || quantity === undefined || quantity === "") return "";
  const symbol = unitSymbol?.trim();
  const amount = formatQuantityValue(quantity, rounding);
  return symbol ? `${amount} ${symbol}` : amount;
}

/**
 * A decimal amount without the zero padding the database carries, and
 * without the tail of a division that never ends.
 *
 * Numeric columns serialize at their full scale ("2.0000", "7.50"), and
 * printing that verbatim claims a precision nobody typed — "12.0000 per
 * batch" reads like a measurement rather than "twelve". Server-side division
 * goes the other way: per-unit amounts arrive as "0.1666666666666666666667",
 * which is 22 digits of noise around one useful number. Anything longer than
 * `maxDecimals` is rounded; a value too small to survive the rounding keeps
 * enough digits to stay non-zero, because "0" would be a different claim.
 * Non-numeric input is returned untouched.
 */
export function formatDecimalQty(
  value: number | string | null | undefined,
  maxDecimals = 4,
): string {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  if (!text.includes(".")) return text;

  const trim = (input: string) => input.replace(/\.?0+$/, "") || "0";
  const decimals = text.split(".")[1].length;
  if (decimals <= maxDecimals) return trim(text);

  const n = Number(text);
  if (!Number.isFinite(n)) return trim(text);
  const rounded = n.toFixed(maxDecimals);
  if (Number(rounded) === 0 && n !== 0) return trim(n.toFixed(8));
  return trim(rounded);
}

/** How many decimals a locale-written quantity keeps before rounding. */
const MAX_QTY_DECIMALS = 4;

/** Below this a value would round away to "0", which is a different claim. */
const TOO_SMALL_TO_ROUND = 10 ** -MAX_QTY_DECIMALS;

/**
 * A decimal-string quantity as this reader writes numbers.
 *
 * The sibling of `formatDecimalQty` above: the same rounding rule, plus the
 * reader's own thousands separator and decimal mark. It lived in the maker
 * module, which is why the rest of the app writes "1234.5" where a Polish
 * reader expects "1234,5".
 *
 * `String(Number(value))` sent the database's own scale straight to the
 * screen — "0.1666666666666666666667" of a kilo — and wrote every number the
 * way JavaScript does rather than the way the language does: no thousands
 * separator anywhere, and a decimal point in the four locales that use a
 * comma.
 *
 * A quantity too small to survive four decimals keeps enough of them to stay
 * non-zero: "0" would say the stock is gone.
 *
 * A caller that counts in fewer places — a recipe's fractions say one — caps
 * the formatter with `maxDecimals`; without it the default stays the
 * app-wide four.
 */
export function formatQuantityLocale(
  value: string | number,
  maxDecimals?: number,
  locale?: string,
): string {
  // Both shapes arrive: a computed number and the wire's Decimal string.
  const text = typeof value === "number" ? String(value) : value;
  const n = Number(text);
  if (text === "" || !Number.isFinite(n)) return text;
  const decimals =
    maxDecimals ??
    (n !== 0 && Math.abs(n) < TOO_SMALL_TO_ROUND ? 8 : MAX_QTY_DECIMALS);
  return new Intl.NumberFormat(locale ?? i18next.language ?? "en", {
    maximumFractionDigits: decimals,
  }).format(n);
}

/**
 * A plain screen number — kilograms, days, kilocalories — as the reader
 * writes it.
 *
 * `toFixed` answers in JavaScript, not in any language: `(0.9).toFixed(1)`
 * prints "0.9" on a screen where every other number reads "0,9", because the
 * string it produced never went through the formatter that knows the
 * reader. The decimal places are fixed — minimum as well as maximum — so a
 * call that replaces `toFixed(n)` keeps the exact shape it printed,
 * including a trailing zero that says the figure was rounded to that many
 * places.
 */
export function formatNumberLocale(
  value: number | string | null | undefined,
  decimals = 2,
  locale?: string,
): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (n == null || !Number.isFinite(n)) return renderEmpty();
  return new Intl.NumberFormat(locale ?? i18next.language ?? "en", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

/** How many decimals a percent keeps before a too-small value widens it. */
const MAX_PERCENT_DECIMALS = 4;

/**
 * Decimal places the value is written with — trailing zeros are not precision.
 *
 * The counterpart of {@link decimalsAllowedBy}, which asks the unit. This one
 * asks the value, and only when the value still has a written form: a string
 * is the figure as it was set down ("20.750" keeps two; the padding is the
 * column's, not the value's). A number has none left — it may be a rate
 * coerced to the double the arithmetic needed, or a percent computed by
 * division, which carries a float's fifteen decimals ("33.333333333333336"
 * for a third) — so the caller's `decimals` decide and no places are
 * invented. Counting off a number's shortest round-trip printed "33,3333%"
 * for a third of a line received, where dev said "33%".
 */
function writtenDecimals(value: number | string | null | undefined): number {
  if (typeof value !== "string") return 0;
  const text = value.trim();
  if (/^-?\d+$/.test(text)) return 0;
  if (/^-?\d+\.\d+$/.test(text)) {
    return text.replace(/\.?0+$/, "").split(".")[1]?.length ?? 0;
  }
  return 0;
}

/**
 * A percentage as the reader writes it — "30,5%" on a Polish screen, with
 * the space French typography keeps before the sign.
 *
 * The value arrives in percent points (30 means 30%), the way every margin
 * and progress figure in the app is stored; `Intl`'s percent style counts in
 * fractions, so it is handed 0.30. Like {@link formatNumberLocale} the
 * `decimals` decide the shape a whole figure keeps — 23 stays "23,0%" when
 * one place was asked for. They are also the precision a *number* is read
 * with, because a number has no written digits left to follow; a *string* —
 * the wire's rate — grows the places to the digits it carries, so "20.75"
 * does not round away into "20,8%", a rate nobody put there.
 */
export function formatPercentLocale(
  value: number | string | null | undefined,
  decimals = 0,
  locale?: string,
): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (n == null || !Number.isFinite(n)) return renderEmpty();
  const asked = Math.max(decimals, writtenDecimals(value));
  const capped = Math.min(MAX_PERCENT_DECIMALS, asked);
  // A value too small to survive the places that will be printed keeps enough
  // of them to stay non-zero: "0%" would say there is nothing there, which is
  // a different claim. The guard has to look at `capped` — the count actually
  // applied — and not at `asked`, or a "0.00001" written with five places
  // slips past the four-place cap and reads "0,0%".
  //
  // How far it grows depends on what the value is. A written string carries
  // its own digits and may run to eight places; a computed number does not —
  // 100/3000 read "0,03333333%" — so it stops at its first significant digit.
  const tooSmall = n !== 0 && Math.abs(n) < 10 ** -capped;
  const significantPlaces = tooSmall
    ? Math.min(8, Math.ceil(-Math.log10(Math.abs(n))))
    : capped;
  const places = !tooSmall
    ? capped
    : typeof value === "string"
      ? Math.max(8, asked)
      : significantPlaces;
  return new Intl.NumberFormat(locale ?? i18next.language ?? "en", {
    style: "percent",
    // Never above the places that will be printed: a request past the cap
    // would be a RangeError from Intl.
    minimumFractionDigits: Math.min(decimals, places),
    maximumFractionDigits: places,
  }).format(n / 100);
}
