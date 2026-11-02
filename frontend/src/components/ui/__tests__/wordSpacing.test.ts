import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * Plus Jakarta Sans draws a space of 170/1000 em. Chrome lays that out as
 * 2.00px at the 14px body size this UI uses everywhere, against 3.64px for
 * system-ui at the same size (measured with canvas `measureText('a a')` minus
 * `measureText('aa')` against the app's own self-hosted subset). At 2px the
 * gap vanishes into the antialiasing and words run together on every screen —
 * "Browse andmanage yourproducts", "3locations · 96products" — in both themes
 * and at both device pixel ratios.
 *
 * `word-spacing` on `:root` is the whole fix: it widens U+0020 and leaves the
 * glyphs, the kerning and the .woff2 files untouched, so the typeface stays as
 * drawn. `letter-spacing` is not the cause and is not the cure — at
 * `letter-spacing: normal` the words merge exactly the same.
 *
 * What this test covers and what it does not: it asserts the declared value
 * clears the floor, so deleting or shaving the declaration turns it red. It
 * cannot see rasterization — no jsdom can — so the rendering evidence is the
 * before/after pair captured on the running app, not this file. The font
 * assertion is here because the number below is a property of *this* typeface:
 * swapping the family without re-measuring the space would leave a threshold
 * that means nothing.
 */

const CSS = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

function rootBlock(): string {
  const start = CSS.indexOf("\n:root {");
  if (start === -1) throw new Error("No :root block in index.css");
  const end = CSS.indexOf("\n}", start);
  return CSS.slice(start, end);
}

function declaration(name: string): string {
  const match = rootBlock().match(new RegExp(`^\\s*${name}:\\s*([^;]+);`, "m"));
  if (!match) throw new Error(`:root declares no ${name}`);
  return match[1].trim();
}

/** The space this font draws, in em — the reason the declaration exists. */
const SPACE_ADVANCE_EM = 0.17;
/**
 * Below roughly 0.2em the gap stops reading as a word break at 14px. system-ui
 * sits at 0.26em; we do not need to reach it, only to clear the floor.
 */
const LEGIBLE_GAP_EM = 0.2;

describe("Word spacing survives the typeface's narrow space", () => {
  it("widens the gap past the point where words merge", () => {
    const value = declaration("word-spacing");
    const em = Number(value.replace(/em$/, ""));

    expect(value, `word-spacing must be an em value, got "${value}"`).toMatch(
      /^[\d.]+em$/,
    );
    expect(SPACE_ADVANCE_EM + em).toBeGreaterThanOrEqual(LEGIBLE_GAP_EM);
  });

  it("reaches the text inside buttons, fields and options", () => {
    // The browser's own stylesheet gives form controls `word-spacing: normal`
    // instead of letting them inherit, and preflight hands back the font and
    // the tracking but not this. Without the rule the label of every button,
    // the search box and each <option> still read "Searchorjumpto…".
    const rule = CSS.match(
      /\n\s*button,\s*input,\s*optgroup,\s*select,\s*textarea\s*\{([^}]*)\}/,
    );
    expect(rule, "no rule for the form controls in index.css").not.toBeNull();
    expect(rule![1]).toMatch(/word-spacing:\s*inherit;/);
  });

  it("is measured against the typeface that made it necessary", () => {
    expect(declaration("font-family").replace(/\s+/g, " ")).toMatch(
      /^"Plus Jakarta Sans"/,
    );
  });
});
