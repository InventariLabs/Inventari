import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/**
 * Classes the module used to carry that compile to nothing.
 *
 * `bg-surface-secondary` and `text-on-surface` look like the real tokens but
 * neither is defined in `tailwind.config.js`, so Tailwind emits no rule and
 * the tint or colour silently does not happen. The theme offers
 * `bg-surface-raised` and `text-on` instead. `text-on-primary` used to belong
 * here; it is a real token now (the brand-text colour on a card, read by
 * `profilePaletteContrast.test.ts`) and recipe links use it.
 */
const DEAD_TOKENS = ["bg-surface-secondary", "text-on-surface"];

const MODULE_ROOT = join(__dirname);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    if (!path.endsWith(".tsx")) return [];
    if (path.endsWith(".test.tsx")) return [];
    return [path];
  });
}

function hits(pattern: string): string[] {
  return sourceFiles(MODULE_ROOT)
    .flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line, i) => ({ line, number: i + 1, path }))
        .filter(({ line }) => line.includes(pattern)),
    )
    .map(({ path, number }) => `${path.replace(MODULE_ROOT, "")}:${number}`);
}

describe("recipes token hygiene", () => {
  it("finds source files at all (the gate is not vacuous)", () => {
    expect(sourceFiles(MODULE_ROOT).length).toBeGreaterThan(50);
  });

  it.each(DEAD_TOKENS)("carries no %s — it compiles to nothing", (token) => {
    expect(hits(token)).toEqual([]);
  });

  // Dark mode flows from the CSS variables the tokens read. A `dark:` override
  // on a class that is already a token is a second, diverging system: the two
  // disagree the moment one of them is edited, and the ramp steps such an
  // override reaches for (`primary-700`) are the ones no theme remaps.
  it("overrides no tokenised class with a dark: variant", () => {
    expect(hits("dark:")).toEqual([]);
  });

  // UI_GUIDELINES §1.1: the status ramps 50…200 flip to dark tints under
  // `.dark` because they carry backgrounds. Reading a step from 500 upwards for
  // the *text* on such a tint gives a dark-on-dark pair in one theme — the
  // class of defect. `text-on-warning` and friends are theme-aware and
  // exist for exactly this pairing.
  const RAMPS = "amber|red|primary|accent|success|blue";
  const TINT = new RegExp(`^bg-(${RAMPS})-(50|100|200)$`);
  const RAMP_TEXT = new RegExp(`^text-(${RAMPS})-[5-9]00$`);

  /**
   * A pair can also hide across states: `text-primary-600` at rest with
   * `hover:bg-primary-50` puts a ramp-step glyph on a flipping tint for the
   * duration of the hover — the same defect, one state later. The fix
   * is a state-scoped text colour (`hover:text-on`), so a state scope that
   * sets a tint but keeps silent on text is what this flags. Only plain
   * interaction states count — an arbitrary variant like `[&_a]:bg-primary-50`
   * styles a different descendant, not a state of the element itself.
   */
  const STATE_VARIANT =
    /^(?:hover|focus|focus-visible|focus-within|active|group-hover|group-focus-within):$/;

  function tintPairs(source: string): string[] {
    const found: string[] = [];
    for (const literal of source.match(/"[^"\n]*"/g) ?? []) {
      const scopes = new Map<string, string[]>();
      for (const cls of literal.slice(1, -1).split(/\s+/).filter(Boolean)) {
        const cut = cls.lastIndexOf(":");
        const scope = cut === -1 ? "" : cls.slice(0, cut + 1);
        const bare = cut === -1 ? cls : cls.slice(cut + 1);
        scopes.set(scope, [...(scopes.get(scope) ?? []), bare]);
      }
      for (const [scope, classes] of scopes) {
        const tint = classes.find((c) => TINT.test(c));
        const text = classes.find((c) => RAMP_TEXT.test(c));
        if (tint && text) found.push(`${scope}${tint} + ${scope}${text}`);
      }
      const base = scopes.get("") ?? [];
      const baseRamp = base.find((c) => RAMP_TEXT.test(c));
      if (baseRamp) {
        for (const [scope, classes] of scopes) {
          if (scope === "" || !STATE_VARIANT.test(scope)) continue;
          const tint = classes.find((c) => TINT.test(c));
          const hasOwnText = classes.some((c) => c.startsWith("text-"));
          if (tint && !hasOwnText) found.push(`${baseRamp} + ${scope}${tint}`);
        }
      }
    }
    return found;
  }

  /**
   * Drained. Kept as an empty list rather than deleted, so that the
   * "no new pairs" assertion below still reads as a baseline gate and a future
   * exception has an obvious, documented place to land.
   */
  const KNOWN_TINT_PAIRS: string[] = [];

  const offending = () =>
    sourceFiles(MODULE_ROOT)
      .filter((path) => tintPairs(readFileSync(path, "utf8")).length > 0)
      .map((path) => path.replace(MODULE_ROOT, ""))
      .sort();

  it("pairs no new tint background with a ramp-step text colour", () => {
    expect(offending().filter((f) => !KNOWN_TINT_PAIRS.includes(f))).toEqual(
      [],
    );
  });

  /**
   * Families absent from `tailwind.config.js`. They still compile — Tailwind
   * ships them by default — but they resolve to fixed hexes that no theme
   * remaps, so they neither follow dark mode nor a profile's repainted ramp.
   * The theme's own families are `primary`, `accent`, `success`, `red`,
   * `amber`, `blue`, `gray` and the `surface`/`on` tokens.
   */
  const FOREIGN_FAMILIES =
    /\b(?:text|bg|border|fill|ring|from|to|via)-(emerald|orange|pink|yellow|green|purple|violet|indigo|sky|cyan|teal|lime|rose|fuchsia|slate|stone|neutral)-[0-9]{2,3}\b/;

  it("paints with the theme's colour families only", () => {
    const offenders = sourceFiles(MODULE_ROOT).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line, i) => ({ line, number: i + 1 }))
        .filter(({ line }) => FOREIGN_FAMILIES.test(line))
        .map(
          ({ line, number }) =>
            `${path.replace(MODULE_ROOT, "")}:${number} → ${line.trim().slice(0, 60)}`,
        ),
    );
    expect(offenders).toEqual([]);
  });

  /**
   * UI_GUIDELINES §4.1: layering is a scale of named tokens, not a race of
   * numbers. A hand-rolled `z-40` backdrop with a `z-50` panel orders itself
   * against sheets and modals by accident, and the `absolute` panel it pairs
   * with is clipped by any ancestor with `overflow-hidden`. Popovers go through
   * a portal at `z-[var(--z-popover)]` — see InlinePopover.
   */
  it("layers popovers on the scale rather than on ad-hoc z-indexes", () => {
    // `z-0` and `z-10` stay allowed: they stack children inside one card and
    // never reach the range where sheets and modals live. From `z-20` up an
    // element is competing with the system layers, and then it needs a token.
    const offenders = sourceFiles(MODULE_ROOT).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line, i) => ({ line, number: i + 1 }))
        .filter(({ line }) => !/^\s*(\*|\/\/|\{\/\*)/.test(line))
        .filter(({ line }) => /\bz-(?!\[)([2-9][0-9]|[0-9]{3,})\b/.test(line))
        .map(
          ({ line, number }) =>
            `${path.replace(MODULE_ROOT, "")}:${number} → ${line.trim().slice(0, 60)}`,
        ),
    );
    expect(offenders).toEqual([]);
  });

  // 12px is the floor (UI_GUIDELINES §1.2). The module had 36 places below it,
  // down to 9px — small enough that the label stops being readable at arm's
  // length, which is exactly where a kitchen screen is held.
  it("sets no type below the 12px floor", () => {
    const offenders = sourceFiles(MODULE_ROOT).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .map((line, i) => ({ line, number: i + 1 }))
        .filter(({ line }) => /text-\[(?:[0-9]|1[01])px\]/.test(line))
        .map(({ number }) => `${path.replace(MODULE_ROOT, "")}:${number}`),
    );
    expect(offenders).toEqual([]);
  });

  it("keeps the baseline honest — a fixed file leaves the list", () => {
    const current = offending();
    expect(KNOWN_TINT_PAIRS.filter((f) => !current.includes(f))).toEqual([]);
  });
});
