import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * A scroller that holds an `sr-only` header must be positioned.
 *
 * `sr-only` is `position: absolute`, so it is placed against the nearest
 * positioned ancestor. Inside an `overflow-x-auto` table scroller with none,
 * it escapes that scroller — and the root's `overflow-x-hidden` with it,
 * because an uncontained absolute element is not clipped by either — and sets
 * the width of the document. Measured on /inventory/lots: a 390px phone grew
 * to 478px, the module's bottom navigation sat below the fold at y=970, and
 * the bell in the header was cut in half by the right edge. The escape is one
 * class away from not existing: `relative` on the scroller makes it the
 * containing block, and the span stops reaching past it.
 *
 * The rule is written at file granularity on purpose: which wrapper the span
 * escapes is a question about markup the regex cannot answer, and a file that
 * puts `sr-only` anywhere near a scroller has the same exposure. A new table
 * with a hidden column header joins the rule without anyone remembering it.
 */
const SRC = join(process.cwd(), "src");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (full.endsWith(".tsx")) out.push(full);
  }
  return out;
}

describe("a scroller holding an sr-only header is positioned", () => {
  it("keeps the absolutely positioned span inside its own box", () => {
    const offenders: string[] = [];

    for (const file of walk(SRC)) {
      const text = readFileSync(file, "utf8");
      if (!text.includes("sr-only")) continue;
      const scrollers = text.matchAll(
        /className="([^"]*\boverflow-x-auto\b[^"]*)"/g,
      );
      for (const match of scrollers) {
        if (!match[1].split(/\s+/).includes("relative")) {
          offenders.push(`${relative(SRC, file)}: ${match[1]}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
