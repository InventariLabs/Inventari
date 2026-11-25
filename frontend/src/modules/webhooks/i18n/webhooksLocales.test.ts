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
  "circuitBreakerWarning_one",
  "circuitBreakerWarning_other",
  "eventsWhileOff",
  "thresholdLink",
  "inactiveCircuitBreaker",
  "testHint",
];

const CAUSE_KEYS = [
  "signingUnreadable",
  "timeout",
  "connectFailed",
  "tlsRefused",
  "connectionBroken",
  "emptyAnswer",
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
