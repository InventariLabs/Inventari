import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * A link or text action on a card takes the brand-text token, not a raw
 * primary step.
 *
 * The raw 600 step measures 3.74:1 on a card in the default light palette and
 * 3.19:1 in `clean_core` — below the 4.5:1 floor for the 14px text these links
 * use. A profile palette remaps the steps again, so no single raw step is
 * readable in every palette; `text-on-primary` is the token that is, and
 * `profilePaletteContrast.test.ts` measures it on every shipped palette and
 * surface. The inset surface is the exception: there the token falls back to
 * the 700 step, 4.31:1, so a link on a `surface-inset` box takes
 * `text-primary-800 dark:text-on-primary` instead.
 *
 * The scan is written for the shape the defect took: a line that paints a
 * link or link-styled action at rest with the raw 600 step. `hover:` and
 * `group-hover:` occurrences are a different state and stay allowed, as do
 * icons, checkbox accents and spinners, whose colour is not text.
 */
const SRC = join(process.cwd(), "src");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (full.endsWith(".tsx") && !full.endsWith(".test.tsx"))
      out.push(full);
  }
  return out;
}

function isComment(line: string): boolean {
  const trimmed = line.trim();
  return (
    trimmed.startsWith("//") ||
    trimmed.startsWith("*") ||
    trimmed.startsWith("/*") ||
    trimmed.startsWith("{/*")
  );
}

/** A rest-state `text-primary-600`, with the hover-only pairs removed. */
function paintsRawRestStep(line: string): boolean {
  const withoutHover = line
    .replace(/group-hover:text-primary-600/g, "")
    .replace(/hover:text-primary-600/g, "");
  return withoutHover.includes("text-primary-600");
}

/** The markup that marks a line as a link or a link-styled action. */
const LINK_MARK = /underline|<Link\b|<a\s|variant="link"/;

/**
 * The wordmark wrapper is a logo, not text: WCAG 1.4.3 exempts logos, and the
 * wordmark inside `BrandLogo` already carries `text-on-primary`, so the
 * wrapper's raw step never paints a glyph.
 */
const LOGO = /<BrandLogo\b/;

describe("links on a card use the brand-text token", () => {
  it("paints no link with the raw primary-600 step", () => {
    const offenders: string[] = [];

    for (const file of walk(SRC)) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, index) => {
        if (isComment(line) || !paintsRawRestStep(line)) return;
        // The element's opening tag can sit on an earlier line, so the
        // link marker is read from the four lines around the className.
        const context = lines
          .slice(Math.max(0, index - 4), index + 4)
          .join("\n");
        if (LOGO.test(context)) return;
        if (LINK_MARK.test(context)) {
          offenders.push(`${relative(SRC, file)}:${index + 1}`);
        }
      });
    }

    expect(offenders).toEqual([]);
  });
});
