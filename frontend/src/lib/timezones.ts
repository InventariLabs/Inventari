// IANA zone names offered when a form asks for the organization's timezone.
//
// The full IANA list (~600 entries) is unusable in a select, so this is a
// curated set covering every inhabited offset — `Pacific/Auckland` is the
// case that motivated the field: a warehouse whose local day tips over
// hours before the server's. The organization's stored zone is always
// selectable even when it is not on the list (see OrganizationSettings).
// The backend validates the value against `zoneinfo` and falls back to UTC
// for anything it cannot read.

export const TIMEZONE_CODES = [
  "UTC",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Africa/Lagos",
  "America/Anchorage",
  "America/Argentina/Buenos_Aires",
  "America/Bogota",
  "America/Chicago",
  "America/Denver",
  "America/Halifax",
  "America/Los_Angeles",
  "America/Mexico_City",
  "America/New_York",
  "America/Phoenix",
  "America/Sao_Paulo",
  "America/Toronto",
  "America/Vancouver",
  "Asia/Bangkok",
  "Asia/Dhaka",
  "Asia/Dubai",
  "Asia/Ho_Chi_Minh",
  "Asia/Hong_Kong",
  "Asia/Jakarta",
  "Asia/Jerusalem",
  "Asia/Kolkata",
  "Asia/Karachi",
  "Asia/Manila",
  "Asia/Seoul",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Asia/Taipei",
  "Asia/Tehran",
  "Asia/Tokyo",
  "Atlantic/Azores",
  "Australia/Brisbane",
  "Australia/Melbourne",
  "Australia/Perth",
  "Australia/Sydney",
  "Europe/Athens",
  "Europe/Berlin",
  "Europe/Brussels",
  "Europe/Dublin",
  "Europe/Helsinki",
  "Europe/Istanbul",
  "Europe/Kyiv",
  "Europe/Lisbon",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Moscow",
  "Europe/Paris",
  "Europe/Prague",
  "Europe/Rome",
  "Europe/Stockholm",
  "Europe/Vienna",
  "Europe/Warsaw",
  "Pacific/Auckland",
  "Pacific/Fiji",
  "Pacific/Honolulu",
  "Pacific/Midway",
] as const;

const offsetFormatterCache = new Map<string, Intl.DateTimeFormat>();

function offsetFor(zone: string): string | null {
  let formatter = offsetFormatterCache.get(zone);
  if (!formatter) {
    try {
      formatter = new Intl.DateTimeFormat("en", {
        timeZone: zone,
        timeZoneName: "shortOffset",
      });
    } catch {
      return null;
    }
    offsetFormatterCache.set(zone, formatter);
  }
  try {
    const name = formatter
      .formatToParts(new Date())
      .find((part) => part.type === "timeZoneName")?.value;
    if (!name) return null;
    // "GMT+2" / "GMT+02:30" / "GMT" → the "UTC" wording users know.
    return name === "GMT" ? "UTC" : name.replace(/^GMT/, "UTC");
  } catch {
    return null;
  }
}

/**
 * A zone shown the way a reader picks it: the IANA name plus its current
 * offset — "Europe/Warsaw (UTC+2)". The offset is the hook the eye scans
 * for; the IANA name is what the setting stores.
 */
export function timezoneLabel(zone: string): string {
  const offset = offsetFor(zone);
  return offset ? `${zone} (${offset})` : zone;
}
