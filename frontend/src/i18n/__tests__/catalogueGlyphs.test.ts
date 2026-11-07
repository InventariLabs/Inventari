/**
 * A catalogue string is words. A check mark or a warning sign typed into one
 * is drawn by the font, not by the design system: it takes the text colour,
 * is announced (or skipped) differently by each screen reader, and the five
 * languages end up with five copies of an icon that belongs in the component.
 * The icon goes in the markup; the catalogue keeps the sentence.
 */
import { describe, expect, it } from "vitest";

const catalogues = import.meta.glob<Record<string, unknown>>(
  ["../locales/*/*.json", "../../modules/*/i18n/*.json"],
  { eager: true, import: "default" },
);

// Emoji and pictographs, the dingbat block (✓ ✔ ✗ ✘ …) and the variation
// selector that turns a plain glyph into an emoji. Arrows and comparison
// signs are typography and stay.
const PICTOGRAPH = /\p{Extended_Pictographic}|[\u2713-\u2718]|\uFE0F/u;

function strings(node: unknown, path: string, out: [string, string][]) {
  if (typeof node === "string") out.push([path, node]);
  else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      strings(value, `${path}.${key}`, out);
    }
  }
}

describe("catalogue strings", () => {
  it("carry no emoji or check-mark glyph", () => {
    const offenders: string[] = [];
    for (const [file, catalogue] of Object.entries(catalogues)) {
      const found: [string, string][] = [];
      strings(catalogue, "", found);
      for (const [path, text] of found) {
        if (PICTOGRAPH.test(text)) offenders.push(`${file}${path}: ${text}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
