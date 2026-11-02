import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, it, expect } from "vitest";

/**
 * `pt-safe-top` and `pb-safe-bottom` read like Tailwind utilities, but this
 * project defines neither, so Tailwind emits nothing for them and the safe-area
 * inset they promise is never applied. The miss is invisible on a desktop and
 * in the simulator — only a phone with a notch or a home indicator shows it.
 * The inset is written with `env(safe-area-inset-*)`, or comes from
 * `SheetFooter`, which carries the bottom one.
 */

// vitest runs with the frontend root as cwd (see statusTokenContrast.test.ts).
const SRC = resolve(process.cwd(), "src");
const UNDEFINED_SAFE_AREA = /\b[mp][tbxy]?-safe-(?:top|bottom|left|right)\b/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.")
      ? [path]
      : [];
  });
}

describe("safe-area insets", () => {
  it("are never written as a utility this project does not define", () => {
    const offenders = sourceFiles(SRC).flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, i) => ({ line, at: `${relative(SRC, file)}:${i + 1}` }))
        .filter(
          ({ line }) =>
            UNDEFINED_SAFE_AREA.test(line) && !line.trim().startsWith("*"),
        )
        .map(({ at }) => at),
    );
    expect(offenders).toEqual([]);
  });
});
