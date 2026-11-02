import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { resolveProfileThemeForMode } from "@/hooks/useProfileTheme";

/**
 * Brand-coloured text (`text-on-primary`) is a different colour in every
 * profile and in each theme: the default palette in index.css, plus the three
 * palettes the backend ships, remapped for dark mode by
 * `resolveProfileThemeForMode`. A test that pins one mocked mapping cannot see
 * a later palette change that drops the brand text under the floor on a
 * surface it actually sits on. This one measures the shipped data itself, on
 * the surfaces and tints the brand text is drawn over — a selected chip is
 * `primary-50` on a card in light, and a translucent `primary-900` over a
 * card or raised surface in dark.
 */

const CSS = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
const PROFILES = readFileSync(
  resolve(process.cwd(), "../backend/app/core/product_profiles.py"),
  "utf8",
);

type Vars = Record<string, string>;
type Rgb = [number, number, number];

function cssBlock(selector: string): Vars {
  const start = CSS.indexOf(`\n${selector} {`);
  if (start === -1) throw new Error(`No ${selector} block in index.css`);
  const body = CSS.slice(start, CSS.indexOf("\n}", start));
  const vars: Vars = {};
  for (const [, name, value] of body.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm)) {
    vars[name] = value.trim();
  }
  return vars;
}

/** `theme={ '--color-…': 'r g b', … }` of every profile, by profile id. */
function shippedThemes(): Record<string, Vars> {
  const themes: Record<string, Vars> = {};
  const entries = [...PROFILES.matchAll(/^ {4}'(\w+)': ProductProfile\(/gm)];
  entries.forEach((entry, i) => {
    const source = PROFILES.slice(
      entry.index,
      entries[i + 1]?.index ?? PROFILES.length,
    );
    const block = /theme=\{([^}]*)\}/.exec(source);
    if (!block) return;
    const theme: Vars = {};
    for (const [, name, value] of block[1].matchAll(
      /'(--[\w-]+)':\s*'([^']+)'/g,
    )) {
      theme[name] = value;
    }
    themes[entry[1]] = theme;
  });
  return themes;
}

const lightBase = cssBlock(":root");
const darkBase = { ...lightBase, ...cssBlock(".dark") };
const THEMES = shippedThemes();

function rgb(vars: Vars, token: string): Rgb {
  const raw = vars[token];
  if (!raw) throw new Error(`Token ${token} is not defined`);
  const channels = raw.split(/\s+/).map(Number);
  if (channels.length !== 3 || channels.some(Number.isNaN)) {
    throw new Error(`Token ${token} is not an "r g b" triple: ${raw}`);
  }
  return channels as Rgb;
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `fg` at `alpha` over `base`, as the browser composites a `bg-x/30` fill. */
function over(fg: Rgb, alpha: number, base: Rgb): Rgb {
  return fg.map((c, i) => c * alpha + base[i] * (1 - alpha)) as Rgb;
}

const AA = 4.5;

/** The palettes under test: the default one, and each shipped profile. */
const PALETTES = [["default", {} as Vars], ...Object.entries(THEMES)] as const;

type Mode = "light" | "dark";

function resolvePalette(theme: Vars, mode: Mode): Vars {
  const base = mode === "dark" ? darkBase : lightBase;
  return { ...base, ...resolveProfileThemeForMode(theme, mode === "dark") };
}

/** The colour `text-on-primary` computes to: the tailwind token falls back to 700. */
function brandText(vars: Vars): Rgb {
  return rgb(
    {
      ...vars,
      "--on-primary": vars["--on-primary"] ?? vars["--color-primary-700"],
    },
    "--on-primary",
  );
}

function surfaces(vars: Vars, mode: Mode): [string, Rgb][] {
  const card = rgb(vars, "--surface-card");
  const raised = rgb(vars, "--surface-raised");
  const found: [string, Rgb][] = [
    ["card", card],
    ["raised surface", raised],
    ["primary-50 tint", rgb(vars, "--color-primary-50")],
    ["primary-100 tint", rgb(vars, "--color-primary-100")],
    ["amber-50 attention card", rgb(vars, "--color-amber-50")],
  ];
  if (mode === "dark") {
    // `dark:hover:bg-primary-900/30` and its relatives.
    const tint = rgb(vars, "--color-primary-900");
    found.push(
      ["primary-900/30 over a card", over(tint, 0.3, card)],
      ["primary-900/30 over a raised surface", over(tint, 0.3, raised)],
    );
  }
  return found;
}

describe("shipped profile palettes", () => {
  it("finds the palettes it is supposed to read", () => {
    // Guards the scan: a refactor of the profile file that matches nothing
    // would turn the cases below into an empty loop that always passes.
    expect(Object.keys(THEMES).length).toBeGreaterThanOrEqual(3);
    for (const theme of Object.values(THEMES)) {
      expect(theme).toHaveProperty("--color-primary-300");
    }
  });

  describe.each(PALETTES)("%s", (_id, theme) => {
    describe.each(["light", "dark"] as const)("%s mode", (mode) => {
      const vars = resolvePalette(theme, mode);
      const text = brandText(vars);

      it.each(surfaces(vars, mode))(
        "brand text reads on a %s at small-text AA",
        (_surface, bg) => {
          expect(ratio(text, bg)).toBeGreaterThanOrEqual(AA);
        },
      );
    });
  });
});
