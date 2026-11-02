// ISO 4217 currency codes offered when a form asks for a currency.
//
// Kept as a plain code list; human-readable labels are resolved at render
// time via `Intl.DisplayNames`, so the list stays localised in all five UI
// languages without duplicating a translation table per language. The same
// set is mirrored in the backend purchase_orders schemas, which reject any
// code outside it.

import type { CountryCode } from "@/lib/countries";

export const CURRENCY_CODES = [
  "AED",
  "AUD",
  "BGN",
  "BRL",
  "CAD",
  "CHF",
  "CNY",
  "CZK",
  "DKK",
  "EUR",
  "GBP",
  "HKD",
  "HUF",
  "ILS",
  "INR",
  "ISK",
  "JPY",
  "KRW",
  "MXN",
  "NOK",
  "NZD",
  "PLN",
  "RON",
  "SEK",
  "SGD",
  "TRY",
  "UAH",
  "USD",
  "ZAR",
] as const;

export type CurrencyCode = (typeof CURRENCY_CODES)[number];

/** Localised currency name for an ISO 4217 code, falling back to the code. */
export function currencyLabel(code: string, locale: string): string {
  try {
    return (
      new Intl.DisplayNames([locale], { type: "currency" }).of(code) ?? code
    );
  } catch {
    return code;
  }
}

const EURO = "EUR";

/**
 * The currency each offered country pays in. Typed over every country the
 * country select lists, so a country added there cannot be left without one;
 * the onboarding guess reads it for whichever country the language or the
 * browser's locale lands on.
 */
export const CURRENCY_BY_COUNTRY: Record<CountryCode, CurrencyCode> = {
  PL: "PLN",
  DE: EURO,
  GB: "GBP",
  US: "USD",
  FR: EURO,
  ES: EURO,
  IT: EURO,
  NL: EURO,
  BE: EURO,
  AT: EURO,
  CH: "CHF",
  CZ: "CZK",
  SK: EURO,
  UA: "UAH",
  LT: EURO,
  LV: EURO,
  EE: EURO,
  SE: "SEK",
  NO: "NOK",
  DK: "DKK",
  FI: EURO,
  IE: EURO,
  LU: EURO,
  PT: EURO,
  GR: EURO,
  HU: "HUF",
  RO: "RON",
  BG: EURO,
  HR: EURO,
  SI: EURO,
  CA: "CAD",
  AU: "AUD",
  NZ: "NZD",
  JP: "JPY",
  CN: "CNY",
  IN: "INR",
  BR: "BRL",
  MX: "MXN",
  TR: "TRY",
  IL: "ILS",
};
