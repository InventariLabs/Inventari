import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { CURRENCY_CODES, currencyLabel } from "@/lib/currencies";

/**
 * The order form's currency select and the backend's currency validation
 * each carry their own curated ISO 4217 list. They used to drift:
 * the backend is a closed frozenset, the frontend a typed array, and nothing
 * compared the two — a code added on one side silently changed what the
 * other side accepts or offers.
 *
 * So the rule is read from the backend instead of restated here: the
 * frontend list must equal the backend set. A new currency lands on one
 * side, this test fails, and both lists follow the code.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_SCHEMAS = path.resolve(
  HERE,
  "../../../../backend/app/modules/purchase_orders/schemas.py",
);

function backendCurrencyCodes(source: string): string[] {
  const block = source.match(
    /CURRENCY_CODES:\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{([^}]*)\}/,
  );
  if (!block) return [];
  return [...block[1].matchAll(/'([A-Z]{3})'/g)].map((m) => m[1]);
}

const backendCodes = backendCurrencyCodes(
  fs.readFileSync(BACKEND_SCHEMAS, "utf8"),
);

describe("currency dictionary parity", () => {
  it("finds the backend list it is supposed to read", () => {
    // Guards the scan itself: a refactor that silently matches nothing
    // would otherwise turn this file into a test that always passes.
    expect(backendCodes.length).toBeGreaterThan(0);
  });

  it("offers exactly the codes the backend accepts", () => {
    expect([...CURRENCY_CODES].sort()).toEqual([...backendCodes].sort());
  });
});

describe("currencyLabel", () => {
  it("resolves a known code to a localised name", () => {
    expect(currencyLabel("PLN", "en")).toBe("Polish Zloty");
    expect(currencyLabel("PLN", "pl")).toBe("złoty polski");
  });

  it("falls back to the code for unknown currencies", () => {
    expect(currencyLabel("DOL", "en")).toBe("DOL");
  });
});
