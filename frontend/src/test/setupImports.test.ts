/**
 * What the test setup imports is part of every test file's import graph, so
 * `vitest related` answers a change to any of it with the whole suite. The
 * setup therefore imports packages and the test infrastructure under
 * `src/test/` only; a test that needs a part of the application imports it
 * itself.
 *
 * Imports, re-exports and dynamic imports of a literal are followed, and so
 * are the targets of `vi.importActual`, `vi.unmock` and `vi.doUnmock`, which
 * Vitest relates like imports (`vitest.` is the same object as `vi.`). Three
 * forms fail whatever they name, because the source text does not settle what
 * they reach: a template with an interpolation; a `vi.mock` without an inline
 * factory, which Vitest may redirect to a `__mocks__` file; and every
 * `import.meta.glob`, with one named exception: the translation-catalog glob
 * of `src/test/mocks/i18n.ts` (one call for the core catalogs, one for the
 * modules'), which loads every catalog on purpose.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const TEST_DIR = resolve(import.meta.dirname);
const SRC_DIR = resolve(TEST_DIR, "..");

/**
 * Static imports and re-exports, then dynamic imports and the `vi` calls that
 * load the real module, whose literal may be a template. `import type` and
 * `export type` bring no module in.
 */
const IMPORT =
  /^(?:import\s+(?!type\b)(?:[^"';]*?\sfrom\s+)?|export\s+(?=[*{])[^"';]*?\sfrom\s+)["']([^"']+)["']|(?:(?<!typeof )\bimport|\bvi(?:test)?\s*\.\s*(?:importActual|unmock|doUnmock)(?:<[\s\S]*?>)?)\(\s*["'`]([^"'`]+)["'`]/gm;

/**
 * A `vi.mock` whose module is not followed by a function written in the call:
 * nothing, an options object, or a name Vitest does not look into.
 */
const MOCK_WITHOUT_FACTORY =
  /\bvi(?:test)?\s*\.\s*mock(?:<[\s\S]*?>)?\(\s*(?:(?:await\s+)?import\(\s*["'`]([^"'`]+)["'`]\s*\)|["'`]([^"'`]+)["'`])(?!\s*,\s*(?:async\b\s*)?(?:\(|function\b|[\w$]+\s*=>))/g;

/** Every glob; the pattern is captured when the call opens with one string. */
const GLOB = /\bimport\.meta\.glob\b(?:<[^(]*>)?(?:\(\s*["']([^"']+)["'])?/g;

const CATALOG_GLOBS = [
  "test/mocks/i18n.ts -> import.meta.glob(../../i18n/locales/*/*.json)",
  "test/mocks/i18n.ts -> import.meta.glob(../../modules/*/i18n/*.json)",
];

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

/**
 * What one file's source reaches: `leaving` names what is outside `src/test/`
 * as `from -> to`, `within` holds the paths still to be read.
 */
function reachedBy(file: string, source: string) {
  const from = file.slice(SRC_DIR.length + 1);
  const leaving: string[] = [];
  const within: string[] = [];
  for (const match of source.matchAll(IMPORT)) {
    const specifier = match[1] ?? match[2];
    let base: string;
    if (specifier.includes("${")) {
      leaving.push(`${from} -> ${specifier}`);
      continue;
    }
    if (specifier.startsWith(".")) base = resolve(dirname(file), specifier);
    else if (specifier.startsWith("@/"))
      base = resolve(SRC_DIR, specifier.slice(2));
    else continue;
    if (base.startsWith(`${TEST_DIR}/`)) within.push(base);
    else leaving.push(`${from} -> ${specifier}`);
  }
  for (const [, imported, literal] of source.matchAll(MOCK_WITHOUT_FACTORY))
    leaving.push(
      `${from} -> vi.mock(${imported ?? literal}) without an inline factory`,
    );
  for (const [, pattern = "no single string"] of source.matchAll(GLOB)) {
    const glob = `${from} -> import.meta.glob(${pattern})`;
    if (!CATALOG_GLOBS.includes(glob)) leaving.push(glob);
  }
  return { leaving, within };
}

/** Every file outside `src/test/` that the setup reaches, as `from -> to`. */
function importsLeavingTheTestDir(entry: string): string[] {
  const seen = new Set<string>();
  const outside: string[] = [];
  const visit = (file: string) => {
    if (seen.has(file) || file.endsWith(".json")) return;
    seen.add(file);
    const { leaving, within } = reachedBy(file, readFileSync(file, "utf8"));
    outside.push(...leaving);
    for (const base of within) visit(resolveFile(base));
  };
  visit(entry);
  return outside;
}

describe("the test setup's imports", () => {
  it("stay inside src/test", () => {
    expect(importsLeavingTheTestDir(resolve(TEST_DIR, "setup.ts"))).toEqual([]);
  });

  const mock = resolve(TEST_DIR, "mocks/browser.ts");

  it.each([
    'export * from "../../modules/stats/module";',
    'export * as stats from "@/modules/stats/module";',
    'export {\n  one,\n  two,\n} from "../../modules/stats/module";',
    'import.meta.glob("../../modules/stats/module.ts", { eager: true });',
    'import.meta.glob<Record<string, unknown>>(\n  "@/modules/*/module.ts",\n);',
    'import.meta.glob(["../../modules/*/module.ts"]);',
    'import.meta.glob("../../i18n/locales/*/*.json");',
    "await import(`../../modules/stats/module`);",
    "await import(`../../modules/${name}/module.ts`);",
    "await import(`./${name}`);",
    "await import(`${directory}/module`);",
    'await vi.importActual("../../modules/stats/module");',
    'await vi.importActual<typeof import("@/modules/stats/module")>(\n  "@/modules/stats/module",\n);',
    'vi.unmock("../../modules/stats/module");',
    "vi.doUnmock(`@/modules/stats/module`);",
    'vi.mock("../../modules/stats/module");',
    'vi.mock("@/modules/stats/module", { spy: true });',
    'vi.mock(import("sonner"));',
    'vi.mock(\n  "sonner",\n);',
    'vi.mock(await import("sonner"));',
    'vi.mock("@/modules/stats/module", statsFactory);',
    'await vitest.importActual("../../modules/stats/module");',
    'vitest.mock("sonner");',
  ])("are seen leaving it in %j", (source) => {
    expect(reachedBy(mock, source).leaving).toHaveLength(1);
  });

  it("let only the translation mock glob outside, and only the catalogs", () => {
    const i18n = resolve(TEST_DIR, "mocks/i18n.ts");
    const catalogs = 'import.meta.glob("../../modules/*/i18n/*.json");';
    const modules = 'import.meta.glob("../../modules/*/module.ts");';
    expect(reachedBy(i18n, catalogs).leaving).toEqual([]);
    expect(reachedBy(i18n, modules).leaving).toHaveLength(1);
  });

  it.each([
    'export * from "./server";',
    "await import(`./server`);",
    'await vi.importActual("./server");',
    'vi.unmock("./server");',
  ])("are followed when they stay inside, as in %j", (source) => {
    expect(reachedBy(mock, source)).toEqual({
      leaving: [],
      within: [resolve(TEST_DIR, "mocks/server")],
    });
  });

  it.each([
    'export type * from "../../modules/stats/module";',
    'export type { Stats } from "../../modules/stats/module";',
    'export const from = "../../modules/stats/module";',
    "type Stats = typeof import(`../../modules/stats/module`);",
    'await vi.importActual("sonner");',
    'vi.mock("../../modules/stats/module", () => ({}));',
    'vi.mock(import("sonner"), async (original) => original());',
    'vi.mock("sonner", async original => original());',
    'vi.mock("sonner", function () {\n  return {};\n});',
  ])("take nothing in from %j", (source) => {
    expect(reachedBy(mock, source)).toEqual({ leaving: [], within: [] });
  });
});
