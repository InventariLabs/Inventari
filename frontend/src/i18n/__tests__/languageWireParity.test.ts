import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { SUPPORTED_LANGUAGES } from "../languages";
import { COMMUNITY_LANGUAGES } from "@/test/languageClasses";

/**
 * The frontend's list of shipped languages and the backend's own list answer
 * to different people: `languages.ts` is what the detector may resolve and
 * the picker offers, `app/i18n/_types.py` is what the API negotiates and
 * what its error catalogs carry. They are two hand-synchronized lists on two
 * sides of the wire — the shape of the currency gate
 * (`lib/__tests__/currencies.test.ts`) and the country gate beside it, for
 * the same reason: a code added on one side silently changes what the other
 * side accepts or offers. The rule is read from the backend instead of
 * restated here: the two sets must be equal.
 *
 * Every code on either side gets a test title of its own, so the red names
 * the language — `it is shipped on both sides` — instead of a general "the
 * lists differ" whose diff is the only clue. The currency gate lets `toEqual`
 * print the codes; a language is small enough to be worth its own line.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_TYPES = path.resolve(
  HERE,
  "../../../../backend/app/i18n/_types.py",
);

function backendLanguageCodes(source: string): string[] {
  const block = source.match(/Language\s*=\s*Literal\[([^\]]*)\]/);
  if (!block) return [];
  return [...block[1].matchAll(/'([a-z]{2})'/g)].map((m) => m[1]);
}

/** The backend's declaration of which languages are community ones. */
function readBackendCommunity(source: string): string[] {
  const block = source.match(/COMMUNITY_LANGUAGES\s*:[^=]*=\s*\(([^)]*)\)/);
  if (!block) return [];
  return [...block[1].matchAll(/'([a-z]{2})'/g)].map((m) => m[1]);
}

const backendSource = fs.readFileSync(BACKEND_TYPES, "utf8");
const backendCodes = backendLanguageCodes(backendSource);
const backendCommunity = readBackendCommunity(backendSource);
const frontendCodes: readonly string[] = SUPPORTED_LANGUAGES;

const everyCode = [...new Set([...frontendCodes, ...backendCodes])].sort();

describe("language list parity across the wire", () => {
  it("finds the backend list it is supposed to read", () => {
    // Guards the scan itself: a refactor that silently matches nothing
    // would otherwise turn this file into a test that always passes.
    expect(backendCodes.length).toBeGreaterThan(0);
  });

  it("declares the same community languages on both sides", () => {
    // The split between maintained and community languages decides which
    // catalogs the gates require in full — the frontend's `community` flag
    // and the backend's `COMMUNITY_LANGUAGES` must say the same thing.
    expect([...backendCommunity].sort()).toEqual(
      [...COMMUNITY_LANGUAGES].sort(),
    );
  });

  for (const code of everyCode) {
    it(`${code} is shipped on both sides`, () => {
      expect(
        frontendCodes.includes(code),
        `frontend/src/i18n/languages.ts does not ship ${code}`,
      ).toBe(true);
      expect(
        backendCodes,
        `backend/app/i18n/_types.py does not ship ${code}`,
      ).toContain(code);
    });
  }
});
