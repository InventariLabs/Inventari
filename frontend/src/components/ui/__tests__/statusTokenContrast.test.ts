import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * The status ramps 50…400 are remapped to dark tints in `.dark` because they
 * carry backgrounds, which left components using the same steps for text with
 * a dark-on-dark pair — the APPROVED badge measured 1.9:1. The `--on-*`
 * foregrounds are the text half of each pair.
 *
 * The assertion is the contrast ratio itself, computed from the token values
 * in index.css: a class-name check would pass again the day someone repoints
 * a token at a shade that does not carry.
 */

// `import.meta.url` is an http URL under the jsdom environment; vitest runs
// with the frontend root as cwd.
// Comments stripped: a token or rule that is commented out must not answer.
const CSS = readFileSync(
  resolve(process.cwd(), "src/index.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

function readBlock(selector: string): Record<string, string> {
  // The blocks are `:root {` / `.dark {` at the start of a line; stop at the
  // first line that closes the block in column zero.
  const start = CSS.indexOf(`\n${selector} {`);
  if (start === -1) throw new Error(`No ${selector} block in index.css`);
  const end = CSS.indexOf("\n}", start);
  const body = CSS.slice(start, end);
  const vars: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm)) {
    vars[name] = value.trim();
  }
  return vars;
}

const light = readBlock(":root");
const dark = { ...light, ...readBlock(".dark") };

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(vars: Record<string, string>, token: string): number {
  const raw = vars[token];
  if (!raw) throw new Error(`Token ${token} is not defined`);
  const [r, g, b] = raw.split(/\s+/).map(Number);
  if ([r, g, b].some(Number.isNaN)) {
    throw new Error(`Token ${token} is not an "r g b" triple: ${raw}`);
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(
  vars: Record<string, string>,
  fg: string,
  bg: string,
): number {
  const a = luminance(vars, fg);
  const b = luminance(vars, bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

const AA = 4.5;

// `-100` is the badge tint; `-50` is the lighter fill used by panels and
// callouts. Both have to carry the same foreground.
const STATUS_PAIRS = [
  ["--on-success", "--color-success-100"],
  ["--on-danger", "--color-red-100"],
  ["--on-warning", "--color-amber-100"],
  ["--on-info", "--color-blue-100"],
  ["--on-success", "--color-success-50"],
  // The import result's "imported" box is accent-tinted: accent mirrors
  // success, and the pair has to hold on its own tints too.
  ["--on-success", "--color-accent-100"],
  ["--on-success", "--color-accent-50"],
  ["--on-danger", "--color-red-50"],
  ["--on-warning", "--color-amber-50"],
  ["--on-info", "--color-blue-50"],
] as const;

describe("status foreground tokens", () => {
  it.each(STATUS_PAIRS)("%s reads on %s in light mode", (fg, bg) => {
    expect(contrast(light, fg, bg)).toBeGreaterThanOrEqual(AA);
  });

  it.each(STATUS_PAIRS)("%s reads on %s in dark mode", (fg, bg) => {
    expect(contrast(dark, fg, bg)).toBeGreaterThanOrEqual(AA);
  });

  // Badges used to switch to `surface-raised` in dark; a caller can still put
  // one there (a badge inside a raised panel), so the pair has to hold.
  it.each(STATUS_PAIRS)("%s reads on a raised surface in dark mode", (fg) => {
    expect(contrast(dark, fg, "--surface-raised")).toBeGreaterThanOrEqual(AA);
  });
});

describe("brand wordmark", () => {
  it("reads on a card in light mode", () => {
    expect(
      contrast(light, "--color-primary-700", "--surface-card"),
    ).toBeGreaterThanOrEqual(AA);
  });

  it("reads on a card in dark mode", () => {
    expect(
      contrast(dark, "--on-primary", "--surface-card"),
    ).toBeGreaterThanOrEqual(AA);
  });
});

// Brand-coloured text. Light mode has no token of its own — the Tailwind
// colour falls back to the ramp's 700, which the wordmark test above holds —
// so what needs pinning is the dark value, on every surface a link sits on.
describe("brand text token in dark mode", () => {
  it.each(["--surface-card", "--surface-raised", "--color-amber-50"])(
    "reads on %s",
    (bg) => {
      expect(contrast(dark, "--on-primary", bg)).toBeGreaterThanOrEqual(AA);
    },
  );

  it("is not set in light mode, so the profile's ramp carries it", () => {
    expect(light).not.toHaveProperty("--on-primary");
  });
});

// The placeholder list of the template editor sits on the raised surface, and
// its descriptions and examples are ten-pixel text. The muted text token
// measured 4.07:1 there in dark and 4.40:1 in light — a token chosen against
// the card, not against the surface the text is actually on. The secondary
// token is what carries it.
describe("small text on the raised surface", () => {
  it("is carried by the secondary text token in both themes", () => {
    expect(
      contrast(light, "--text-secondary", "--surface-raised"),
    ).toBeGreaterThanOrEqual(AA);
    expect(
      contrast(dark, "--text-secondary", "--surface-raised"),
    ).toBeGreaterThanOrEqual(AA);
  });

  it("is not carried by the muted token, which falls short there", () => {
    // Documents why the editor does not use it: if a palette change lifts
    // muted over the floor this test says so and the choice can be revisited.
    expect(contrast(dark, "--text-muted", "--surface-raised")).toBeLessThan(AA);
  });
});

// The neutral mass of a composition bar sits on the bar's own track. It is a
// graphic, not text, so the floor is the 3:1 of WCAG 1.4.11 — and the pair
// matters because the neutral mass is most of the bar: at the lighter zinc
// the mockup started from, a zone full of products read as an empty track.
const NON_TEXT = 3;

describe("composition bar neutral segment", () => {
  it("stands out from its track in light mode", () => {
    expect(
      contrast(light, "--bar-ok", "--surface-inset"),
    ).toBeGreaterThanOrEqual(NON_TEXT);
  });

  it("stands out from its track in dark mode", () => {
    expect(
      contrast(dark, "--bar-ok", "--surface-inset"),
    ).toBeGreaterThanOrEqual(NON_TEXT);
  });
});

// "Issued" sits beside the neutral mass on the same track, and most of an IT
// fleet is issued on most days — the colour carries the bar's main answer.
describe("composition bar active segment", () => {
  it("stands out from its track in light mode", () => {
    expect(
      contrast(light, "--bar-active", "--surface-inset"),
    ).toBeGreaterThanOrEqual(NON_TEXT);
  });

  it("stands out from its track in dark mode", () => {
    expect(
      contrast(dark, "--bar-active", "--surface-inset"),
    ).toBeGreaterThanOrEqual(NON_TEXT);
  });
});

// A card's text link (CardLink) takes the wordmark's pair, and the amber
// attention card is the darkest surface it sits on in either theme.
describe("card link on the attention card", () => {
  it("reads on the amber tint in light mode", () => {
    expect(
      contrast(light, "--color-primary-700", "--color-amber-50"),
    ).toBeGreaterThanOrEqual(AA);
  });

  it("reads on the amber tint in dark mode", () => {
    expect(
      contrast(dark, "--on-primary", "--color-amber-50"),
    ).toBeGreaterThanOrEqual(AA);
  });
});
