import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { COUNTRY_CODES, countryLabel, isCountryCode } from "@/lib/countries";

/**
 * The address form offers a curated country list, the backend validates
 * against the full ISO 3166-1 set, and PDFs print names through Babel's
 * CLDR tables ( follow-up). The three used to be three hand-kept
 * copies; the gate that matters is: the form must never offer a code the
 * API would reject, and every offered code must resolve to a real name.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_DTOS = path.resolve(
  HERE,
  "../../../../backend/app/core/contracts/_core_dtos.py",
);

function backendIsoCodes(source: string): string[] {
  const block = source.match(
    /ISO_3166_ALPHA2_CODES:\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{([^}]*)\}/,
  );
  if (!block) return [];
  return [...block[1].matchAll(/'([A-Z]{2})'/g)].map((m) => m[1]);
}

const isoCodes = backendIsoCodes(fs.readFileSync(BACKEND_DTOS, "utf8"));
const isoSet = new Set(isoCodes);

describe("country dictionary parity ( follow-up)", () => {
  it("finds the backend ISO list it is supposed to read", () => {
    // Guards the scan itself: a refactor that silently matches nothing
    // would otherwise turn this file into a test that always passes.
    expect(isoCodes.length).toBeGreaterThan(200);
  });

  it("offers only codes the API accepts", () => {
    const rejected = COUNTRY_CODES.filter((code) => !isoSet.has(code));
    expect(rejected).toEqual([]);
  });

  it("resolves every offered code to a name", () => {
    for (const code of COUNTRY_CODES) {
      expect(isCountryCode(code)).toBe(true);
      const name = countryLabel(code, "en");
      expect(name).not.toBe(code);
      expect(name.length).toBeGreaterThan(2);
    }
  });
});
