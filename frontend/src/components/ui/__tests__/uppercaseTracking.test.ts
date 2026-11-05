import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * Uppercase text with `tracking-tight` / `tracking-tighter` closes its word
 * spaces: the -0.025em / -0.05em tracking comes off a gap that is already
 * narrow in this typeface (see wordSpacing.test.ts), and capitals have no
 * ascenders to bridge it — "AISLE A" read "AISLEA" on the statistics screen.
 * The fix is one rule in index.css; this test fails when it is removed or
 * stops covering either utility. Rasterization is out of reach of jsdom, so
 * the rendered before/after lives with the change, not here.
 */

const CSS = readFileSync(
  resolve(process.cwd(), "src/index.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

function uppercaseRule(): { selector: string; body: string } {
  const match = CSS.match(/\n([^{}\n][^{}]*\.uppercase[^{}]*)\{([^}]*)\}/);
  if (!match) throw new Error("index.css has no rule for uppercase tracking");
  return { selector: match[1], body: match[2] };
}

describe("Uppercase text keeps normal tracking", () => {
  it("overrides tracking-tight and tracking-tighter on .uppercase", () => {
    const { selector } = uppercaseRule();
    expect(selector).toContain(".uppercase.tracking-tight");
    expect(selector).toContain(".uppercase.tracking-tighter");
  });

  it("resets the letter-spacing to normal", () => {
    expect(uppercaseRule().body).toMatch(/letter-spacing:\s*normal;/);
  });

  it("outranks the utilities with a compound selector, not by source order", () => {
    // `.tracking-tight` alone is one class; the override needs two.
    for (const part of uppercaseRule().selector.split(",")) {
      expect(part.trim().split(".").length - 1).toBeGreaterThanOrEqual(2);
    }
  });
});
