import { describe, expect, it } from "vitest";

import de from "./de.json";
import en from "./en.json";
import es from "./es.json";
import fr from "./fr.json";
import pl from "./pl.json";
import pt from "./pt.json";

/**
 * The sentences a failed webhook shows are advice the reader acts on. A key
 * present in every language passes the i18n gates even when a language still
 * carries the English words, so these tests compare the sentences themselves.
 */

type Bundle = Record<string, unknown>;

const OTHER_LANGUAGES: Array<[string, Bundle]> = [
  ["pl", pl],
  ["de", de],
  ["fr", fr],
  ["es", es],
  ["pt", pt],
];

function read(bundle: Bundle, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (node, key) => (node as Bundle | undefined)?.[key],
      bundle,
    );
}

const BANNER_KEYS = [
  "eventsWhileOff",
  "thresholdLink",
  "inactiveCircuitBreaker",
  "testHint",
];

/**
 * The banner is a plural: every form a maintained language selects for a
 * count the banner can show (a tripped endpoint has failed at least three
 * times) must be a sentence of that language, not the English one.
 */
const BANNER_COUNTS = [3, 4, 5, 11, 22, 25, 100, 1000000];

function bannerForms(language: string): string[] {
  const rules = new Intl.PluralRules(language);
  return [...new Set(BANNER_COUNTS.map((count) => rules.select(count)))].map(
    (form) => `circuitBreakerWarning_${form}`,
  );
}

const CAUSE_KEYS = [
  "signingUnreadable",
  "timeout",
  "connectFailed",
  "tlsRefused",
  "connectionBroken",
  "emptyAnswer",
  "urlLoopback",
  "urlPrivate",
  "urlUnresolved",
  "urlRebinding",
  "urlMalformed",
  "urlScheme",
  "urlNoHostname",
].map((key) => `delivery.cause.${key}`);

describe("webhook sentences in every language", () => {
  it.each([...BANNER_KEYS, ...CAUSE_KEYS])(
    "%s is translated, not left in English",
    (key) => {
      const english = read(en, key);
      expect(typeof english).toBe("string");
      for (const [language, bundle] of OTHER_LANGUAGES) {
        const text = read(bundle, key);
        expect(text, `${language}: ${key}`).toEqual(expect.any(String));
        expect(
          text,
          `${language}: ${key} is still the English sentence`,
        ).not.toBe(english);
      }
    },
  );
});

describe("the circuit-breaker banner in every plural form", () => {
  it.each(OTHER_LANGUAGES)(
    "%s words every form it selects",
    (language, bundle) => {
      const forms = bannerForms(language);
      expect(forms.length).toBeGreaterThan(0);
      for (const key of forms) {
        const text = bundle[key];
        expect(text, `${language}: ${key}`).toEqual(expect.any(String));
        expect(
          text,
          `${language}: ${key} is still the English sentence`,
        ).not.toBe((en as Bundle)["circuitBreakerWarning_other"]);
      }
    },
  );

  it("covers pl few and many, and fr many", () => {
    expect(bannerForms("pl")).toEqual(
      expect.arrayContaining([
        "circuitBreakerWarning_few",
        "circuitBreakerWarning_many",
      ]),
    );
    expect(bannerForms("fr")).toContain("circuitBreakerWarning_many");
  });
});
