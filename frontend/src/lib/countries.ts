// ISO 3166-1 alpha-2 country codes offered in address forms.
//
// Kept as a plain code list; human-readable labels are resolved at render time
// via `Intl.DisplayNames`, so the list stays localised in all five UI
// languages without duplicating a translation table per language.

export const COUNTRY_CODES = [
  "PL",
  "DE",
  "GB",
  "US",
  "FR",
  "ES",
  "IT",
  "NL",
  "BE",
  "AT",
  "CH",
  "CZ",
  "SK",
  "UA",
  "LT",
  "LV",
  "EE",
  "SE",
  "NO",
  "DK",
  "FI",
  "IE",
  "LU",
  "PT",
  "GR",
  "HU",
  "RO",
  "BG",
  "HR",
  "SI",
  "CA",
  "AU",
  "NZ",
  "JP",
  "CN",
  "IN",
  "BR",
  "MX",
  "TR",
  "IL",
] as const;

export type CountryCode = (typeof COUNTRY_CODES)[number];

const CODE_SET: ReadonlySet<string> = new Set<string>(COUNTRY_CODES);

/** True when *value* is one of the ISO alpha-2 codes in the curated list. */
export function isCountryCode(
  value: string | null | undefined,
): value is CountryCode {
  return !!value && CODE_SET.has(value);
}

/** Localised country name for an ISO alpha-2 code, falling back to the code. */
export function countryLabel(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * The country a browser locale suggests, when it is one the list offers.
 *
 * A bare language ("pl") resolves through its most likely region, the way the
 * interface language already guesses a currency; a locale the runtime cannot
 * parse, or a region outside the list, suggests nothing.
 */
export function countryFromLocale(
  locale: string | null | undefined,
): CountryCode | null {
  if (!locale) return null;
  try {
    const region = new Intl.Locale(locale).maximize().region;
    return isCountryCode(region) ? region : null;
  } catch {
    return null;
  }
}
