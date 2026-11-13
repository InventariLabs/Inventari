import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BLOCKING, DETECTORS } from "./index.mjs";

// Resolved from the working directory: under vitest `import.meta.url` is not a file URL.
const here = `${process.cwd()}/scripts/ui-patterns/`;

/**
 * The gate's membership, spelled out. Taking a detector out of BLOCKING — or
 * adding one — has to change this list in the same commit, so it is a decision
 * somebody read rather than a line that slipped out of a diff.
 */
const EXPECTED_BLOCKING = [
  "border-weight",
  "button-icon-size",
  "button-size-override",
  "contrast-wash",
  "content-size-unpadded",
  "destructive-as-neutral",
  "destructive-outside-confirm",
  "detail-not-found",
  "disclosure-indicator",
  "error-message-as-copy",
  "failure-as-empty",
  "field-box-class",
  "field-row-baseline",
  "flex-1-in-a-column",
  "format-without-locale",
  "footer-action-rows",
  "footer-half-width",
  "heavy-weight",
  "hover-only-reveal",
  "icon-button-unnamed",
  "label-line-box",
  "label-without-field",
  "money-unformatted",
  "money-without-currency",
  "native-date-input",
  "numeric-z-index",
  "overflow-row",
  "sheet-scroll-layer",
  "slate-palette-literal",
  "success-palette-literal",
  "write-action-ungated",
];

describe("BLOCKING", () => {
  it("is exactly the pinned set — a detector leaving or joining must say so here", () => {
    expect([...BLOCKING].sort()).toEqual([...EXPECTED_BLOCKING].sort());
  });

  it("names no detector twice in its source (a Set hides the duplicate)", () => {
    const source = readFileSync(`${here}index.mjs`, "utf8");
    const block = source.match(/export const BLOCKING = new Set\(\[([\s\S]*?)\]\)/);
    const names = [...block[1].matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]);

    expect(names.length).toBeGreaterThan(0);
    expect(names.filter((n, i) => names.indexOf(n) !== i)).toEqual([]);
  });

  it("names only detectors that exist", () => {
    const known = new Set(DETECTORS.map((d) => d.name));

    expect([...BLOCKING].filter((name) => !known.has(name))).toEqual([]);
  });

  it("gives every blocking detector a spec file of its own", () => {
    const missing = [...BLOCKING].filter((name) => {
      try {
        readFileSync(`${here}${name}.test.mjs`);
        return false;
      } catch {
        return true;
      }
    });

    expect(missing).toEqual([]);
  });
});
