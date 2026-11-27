/**
 * What the test setup imports is part of every test file's import graph, so
 * `vitest related` answers a change to any of it with the whole suite. The
 * setup therefore imports packages and the test infrastructure under
 * `src/test/` only; a test that needs a part of the application imports it
 * itself.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const TEST_DIR = resolve(import.meta.dirname);
const SRC_DIR = resolve(TEST_DIR, "..");

/** Static and literal dynamic imports; `import type` brings no module in. */
const IMPORT =
  /^import\s+(?!type\b)(?:[^"';]*?\sfrom\s+)?["']([^"']+)["']|(?<!typeof )\bimport\(\s*["']([^"']+)["']/gm;

function resolveFile(base: string): string {
  for (const suffix of ["", ".ts", ".tsx"]) {
    try {
      readFileSync(base + suffix);
      return base + suffix;
    } catch {
      // Not this spelling.
    }
  }
  throw new Error(`Cannot resolve ${base}`);
}

/** Every file outside `src/test/` that the setup reaches, as `from -> to`. */
function importsLeavingTheTestDir(entry: string): string[] {
  const seen = new Set<string>();
  const outside: string[] = [];
  const visit = (file: string) => {
    if (seen.has(file) || file.endsWith(".json")) return;
    seen.add(file);
    for (const match of readFileSync(file, "utf8").matchAll(IMPORT)) {
      const specifier = match[1] ?? match[2];
      let base: string;
      if (specifier.startsWith(".")) base = resolve(dirname(file), specifier);
      else if (specifier.startsWith("@/"))
        base = resolve(SRC_DIR, specifier.slice(2));
      else continue;
      if (base.startsWith(`${TEST_DIR}/`)) visit(resolveFile(base));
      else outside.push(`${file.slice(SRC_DIR.length + 1)} -> ${specifier}`);
    }
  };
  visit(entry);
  return outside;
}

describe("the test setup's imports", () => {
  it("stay inside src/test", () => {
    expect(importsLeavingTheTestDir(resolve(TEST_DIR, "setup.ts"))).toEqual([]);
  });
});
