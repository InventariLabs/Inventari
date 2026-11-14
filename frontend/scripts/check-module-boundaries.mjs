#!/usr/bin/env node
/**
 * check-module-boundaries.mjs
 *
 * Records which modules reach into which other modules, and fails on new ones.
 *
 * AGENTS.md states the rule: a module talks to another module through its one
 * public API, and never by importing its internals. Nothing enforced it on the
 * frontend, so the nutrition module scanned photos by importing the stats
 * module's API client — a call that has nothing to do with statistics and
 * broke the moment stats was disabled.
 *
 * The same file records the second boundary: a module reaches Core through
 * `@/module-sdk` and through nothing else. `module-sdk` re-exports the registry,
 * its contract types, the API client, the design system and the hooks a module
 * screen needs; an `@/components/ui/Button` import in a module file is the
 * doorway the SDK exists to close. The modules written before the SDK existed
 * keep the paths they already use, recorded per module and specifier — a path
 * a module has never used is a new finding, and `example_widgets`, the module
 * new authors copy, has no such entry at all. The granularity is the module's
 * dependency surface rather than the importing file: a new screen may use a
 * core path its own module already depends on, and no module may acquire a new
 * one without an answer.
 *
 * Two layers are shared by design and never counted (AGENTS.md,
 * "Module-First File Placement"):
 *   - `shared`   — cross-vertical building blocks
 *   - `settings` — the organization, the module registry, the product profile
 *
 * Specs are not counted either: a test reaching for another module's fixture
 * says nothing about how the application is wired.
 *
 * Two forms are out of scope, and the gate says so rather than leaving the
 * silence to be read as coverage:
 *   - `require("…")` — the tree is ESM; a CommonJS require is a build error
 *     before it is an edge, and the gate does not police a form the build
 *     never sees.
 *   - a specifier carrying `${…}` — a substitution names its target at
 *     runtime, not at scan time. A backtick specifier with nothing
 *     substituted is static, and is counted like any quoted one: the
 *     delimiter is not what the gate reads.
 *   - a relative specifier is resolved against the importing file rather than
 *     skipped: a hop into another module is counted as the edge it is, and a
 *     hop out of `src/modules` into Core is recorded as the `@/…` entry the
 *     alias names. The import convention (frontend/AGENTS.md §5) keeps
 *     relative specifiers inside a module, but one that steps out must not be
 *     a second, unrecorded way through the door.
 *
 * The baseline is deliberately NOT registered in check-suppressions.mjs. The
 * baselines it guards are lists of debt — every entry is a finding somebody
 * owes an answer for. This one is a map of what the app is wired like today,
 * and most of its edges are legitimate (equipment reads locations, documents
 * read partners). Freezing the map is the point; owning each line of it is
 * not. What must not happen quietly is a new edge, and that is what fails.
 *
 * Modes:
 *   node check-module-boundaries.mjs                  # full report, exit 1
 *   node check-module-boundaries.mjs --baseline       # fail only on NEW edges
 *   node check-module-boundaries.mjs --write-baseline # refresh the record
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const MODULES = resolve(ROOT, "src/modules");
const BASELINE_PATH = resolve(ROOT, "scripts/module-boundaries-baseline.json");

/** Layers every module may lean on — see the header. */
export const SHARED_LAYERS = new Set(["shared", "settings"]);

/**
 * A specifier pointing into a module, however it is reached: `from
 * "@/modules/stats/api"`, `import("@/modules/stats/api")`, `export * from`.
 * The old pattern demanded `from\s+`, so a lazy `import()` — the commonest
 * way a module pulls another module's pages — was invisible to the gate.
 *
 * All three delimiters are read: a backtick specifier with no substitution
 * is as static as a quoted one, and nothing normalises it into a quote —
 * there is no `quotes` rule here and prettier leaves backticks alone. The
 * lookahead skips a specifier that carries `${…}`; see the header.
 */
const ALIAS_SPECIFIER_RE =
  /["'`](?![^"'`\n]*\$\{)@\/modules\/([a-z_]+)((?:\/[^"'`\n]*)?)["'`]/g;

/**
 * The one file a module publishes for the modules that depend on it
 * (`src/modules/<name>/moduleApi.ts`). Reaching it is not an edge: it is the
 * door the owner keeps stable and documents in FRONTEND_MODULE_GUIDE, the
 * frontend counterpart of a backend module's `*_api`. Everything else under
 * the module stays internal, and an import of it is counted as before.
 */
export const MODULE_API_FILE = "moduleApi";

/**
 * A relative specifier, static or dynamic, quoted or backticked: `from
 * "../spaces/api"` and `import("../stock_takes/pages/X")` are the same edge
 * written without the alias. Resolved against the importing file's directory
 * below, because whether `../../x` leaves the module depends on how deep the
 * file sits. Same substitution rule as the alias pattern above.
 */
const RELATIVE_SPECIFIER_RE =
  /(?:from\s+|import\(\s*)["'`](?![^"'`\n]*\$\{)(\.[^"'`]+)["'`]/g;

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isCountedFile(rel) {
  if (!/\.(ts|tsx)$/.test(rel)) return false;
  if (/\.test\.tsx?$/.test(rel)) return false;
  if (rel.includes("__tests__/")) return false;
  return true;
}

/** Modules a file reaches into, minus its own and the shared layers. */
export function crossings(rel, text, modules = new Set()) {
  const owner = rel.split("/")[0];
  const dir = rel.split("/").slice(0, -1);
  const found = new Set();

  const add = (target) => {
    if (!target || target === owner) return;
    if (SHARED_LAYERS.has(target)) return;
    found.add(target);
  };

  for (const match of text.matchAll(ALIAS_SPECIFIER_RE)) {
    if (match[2] === `/${MODULE_API_FILE}`) continue;
    add(match[1]);
  }

  for (const match of text.matchAll(RELATIVE_SPECIFIER_RE)) {
    const parts = [...dir];
    for (const segment of match[1].split("/")) {
      if (segment === "." || segment === "") continue;
      if (segment === "..") parts.pop();
      else parts.push(segment);
    }
    const target = parts[0];
    if (parts.length === 2 && parts[1] === MODULE_API_FILE) continue;
    // A relative hop counts only when it lands inside a known module —
    // `../../components/…` out of modules/ entirely is nobody's edge. The
    // module set comes from the corpus; a caller that passes none cannot
    // verify the landing spot, and the safe default for a control tool is to
    // count the hop: an edge dropped in silence is the failure this gate
    // exists to prevent.
    if (modules.size > 0 && !modules.has(target)) continue;
    add(target);
  }

  return [...found].sort().map((target) => `${rel} → ${target}`);
}

export function edgesIn(files, readFile) {
  const modules = new Set(files.map((rel) => rel.split("/")[0]));
  const edges = [];
  for (const rel of files) {
    if (!isCountedFile(rel)) continue;
    edges.push(...crossings(rel, readFile(rel), modules));
  }
  return edges.sort();
}

/** The one specifier a module may use to reach Core. */
export const MODULE_SDK = "@/module-sdk";

/**
 * The one other specifier a module may write: the declaration that adds its
 * own slot to `SlotDataMap`,
 *
 *     declare module "@/lib/moduleRegistry/slotProps" {
 *       interface SlotDataMap { my_slot: { … } }
 *     }
 *
 * TypeScript merges an interface only through the module that declares it, so
 * the SDK's re-export cannot carry it. It is a type-level extension point the
 * SDK documents, not an import of Core internals, and it spares a module that
 * renders a place for others to fill from editing `slotProps.ts`.
 */
const SLOT_AUGMENTATION_RE =
  /declare\s+module\s+["']@\/lib\/moduleRegistry\/slotProps["']/g;

const CORE_ALIAS_RE = /["'`](?![^"'`\n]*\$\{)@\/([A-Za-z0-9_./-]+)["'`]/g;

/**
 * A relative import, static or dynamic, quoted or backticked, as written:
 * `from "../../lib/api/client"`, `import("../../components/ui/Button")`.
 * A side-effect import (`import "../../x"`) is the same edge. Same
 * substitution rule as the module-edge pattern: a `${…}` names its target at
 * runtime, not at scan time.
 */
const RELATIVE_IMPORT_RE =
  /(?:from\s+|import\s*\(\s*|import\s+)["'`](?![^"'`\n]*\$\{)(\.[^"'`]*)["'`]/g;

/**
 * The `@/…` entry a relative specifier resolves to, or `undefined` when it
 * stays inside the module or lands in another one (the first rule's business).
 *
 * The import convention keeps relative specifiers inside a module, but a valid
 * one can still step out of `src/modules` — `../../lib/api/client` from
 * `example_widgets/module.ts` is the same file as `@/lib/api/client`. Reading
 * only the alias would leave that spelling as an open door around the SDK.
 */
function canonicalCoreSpecifier(rel, specifier) {
  const parts = ["src", "modules", ...rel.split("/").slice(0, -1)];
  for (const segment of specifier.split("/")) {
    if (segment === "." || segment === "") continue;
    if (segment === "..") {
      parts.pop();
      continue;
    }
    parts.push(segment);
  }
  if (parts[0] !== "src" || parts.length < 2) return undefined;
  if (parts[1] === "modules") return undefined;
  const path = parts
    .slice(1)
    .join("/")
    .replace(/\.(tsx?|jsx?|mjs)$/, "")
    .replace(/\/index$/, "");
  return path ? `@/${path}` : undefined;
}

/**
 * Core paths a module file imports outside the SDK, as `module → @/path`.
 *
 * Module-to-module specifiers (`@/modules/…`) are the first rule's business,
 * and the SDK itself is the door. Everything else is Core, and a module that
 * imports it directly depends on an internal path that may move without a
 * module author ever hearing about it. A relative specifier is resolved
 * against the importing file and recorded as the same entry the alias names,
 * so the two spellings cannot disagree.
 */
export function coreImports(rel, text) {
  const owner = rel.split("/")[0];
  const found = new Set();
  text = text.replace(SLOT_AUGMENTATION_RE, "");
  for (const match of text.matchAll(CORE_ALIAS_RE)) {
    const path = match[1];
    if (`@/${path}` === MODULE_SDK || path.startsWith("modules/")) continue;
    found.add(`@/${path}`);
  }
  for (const match of text.matchAll(RELATIVE_IMPORT_RE)) {
    const canonical = canonicalCoreSpecifier(rel, match[1]);
    if (canonical) found.add(canonical);
  }
  return [...found].sort().map((specifier) => `${owner} → ${specifier}`);
}

export function coreImportsIn(files, readFile) {
  const imports = [];
  for (const rel of files) {
    if (!isCountedFile(rel)) continue;
    imports.push(...coreImports(rel, readFile(rel)));
  }
  return [...new Set(imports)].sort();
}

function readBaseline() {
  const baseline = existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
    : {};
  return {
    edges: new Set(baseline.edges ?? []),
    coreImports: new Set(baseline.coreImports ?? []),
  };
}

function reportFresh(label, fresh, nextStep) {
  console.error(`${label}: ${fresh.length} NEW import(s) across a boundary\n`);
  for (const entry of fresh) console.error(`  ${entry}`);
  console.error(`\n${nextStep}`);
}

function main() {
  const files = walk(MODULES).map((f) =>
    relative(MODULES, f).split("\\").join("/"),
  );
  const read = (rel) => readFileSync(resolve(MODULES, rel), "utf8");
  const edges = edgesIn(files, read);
  const core = coreImportsIn(files, read);
  const args = process.argv.slice(2);

  if (args.includes("--write-baseline")) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify({ edges, coreImports: core }, null, 2) + "\n",
    );
    console.log(
      `module-boundaries baseline written: ${edges.length} edge(s), ` +
        `${core.length} core import(s) → scripts/module-boundaries-baseline.json`,
    );
    process.exit(0);
  }

  if (args.includes("--baseline")) {
    const baseline = readBaseline();
    const freshEdges = edges.filter((e) => !baseline.edges.has(e));
    const freshCore = core.filter((e) => !baseline.coreImports.has(e));

    if (freshEdges.length > 0 || freshCore.length > 0) {
      if (freshEdges.length > 0)
        reportFresh(
          "module-boundaries",
          freshEdges,
          "Go through the module's public API, move the shared piece into " +
            "src/modules/shared, or lift it to Core. Do NOT grandfather it.",
        );
      if (freshCore.length > 0)
        reportFresh(
          "module-boundaries (core)",
          freshCore,
          "Import the name from @/module-sdk. If the SDK does not export it " +
            "yet, add it there — that is a supported, additive change — and " +
            "import it from the module. Do NOT grandfather the path.",
        );
      process.exit(1);
    }

    const healed = [...baseline.edges].filter((b) => !edges.includes(b));
    const healedCore = [...baseline.coreImports].filter(
      (b) => !core.includes(b),
    );
    const healedNote =
      healed.length + healedCore.length > 0
        ? `, ${healed.length + healedCore.length} removed since baseline. ` +
          "Run --write-baseline to refresh."
        : ".";
    console.log(
      `module-boundaries passed baseline: ${edges.length} known edge(s), ` +
        `${core.length} known core import(s)${healedNote}`,
    );
    process.exit(0);
  }

  console.log(
    `module-boundaries: ${edges.length} edge(s), ${core.length} core import(s)`,
  );
  for (const edge of edges) console.log(`  ${edge}`);
  for (const entry of core) console.log(`  ${entry}`);
  process.exit(edges.length > 0 || core.length > 0 ? 1 : 0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
