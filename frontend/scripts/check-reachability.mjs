#!/usr/bin/env node
/**
 * check-reachability.mjs
 *
 * Detects source files no production entry point can reach.
 *
 * knip already asks "is this file imported?" — and answers yes for a
 * component whose only importer is its own spec, because knip.json declares
 * `src/**\/*.test.{ts,tsx}` an entry point. The effect is perverse: the more
 * diligently a feature is tested, the more effectively it hides. This gate
 * asks a different question — "can the running app reach it?" — by walking
 * the import graph from the PRODUCTION roots only. Specs are consumers here,
 * like any other file, never roots.
 *
 * A file that is unreachable AND imported by a spec gets its own marker: that
 * is not ordinary dead code, it is a feature somebody wrote, tested, and never
 * wired up.
 *
 * Modes:
 *   node check-reachability.mjs                   # full report, exit 1
 *   node check-reachability.mjs --baseline        # only NEW findings fail
 *   node check-reachability.mjs --write-baseline  # snapshot current state
 *
 * Baseline: frontend/scripts/reachability-baseline.json
 * The goal is an EMPTY baseline — wire the file up or delete it, don't
 * grandfather it.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, dirname, relative, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/reachability-baseline.json");

// ---------------------------------------------------------------------------
// Production roots — every entry point the shipped bundle starts from.
// main.tsx boots the app; App.tsx holds the static route table; each module.ts
// self-registers on import; the design system under components/ui is public
// surface consumed ad-hoc by any module (same rationale as knip.json's entry
// list, kept in sync with it deliberately).
// ---------------------------------------------------------------------------
const ROOT_PATTERNS = [
  "main.tsx",
  "App.tsx",
  "lib/moduleRegistry.ts",
  /^modules\/[^/]+\/module\.ts$/,
  /^components\/ui\/[^/]+\.tsx$/,
];

// Files that are never reported, each for a stated reason.
const EXEMPT = [
  // Generated from the backend OpenAPI schema, checked in for the type
  // checker; nothing imports it at runtime by design.
  "types/api-generated.ts",
  // Legitimately test-only: it feeds the API contract smoke test, which is
  // the whole point of generating it.
  "types/api-routes.ts",
];

const isSpec = (rel) =>
  /\.test\.tsx?$/.test(rel) ||
  rel.startsWith("test/") ||
  rel.includes("__mocks__/");

const isSource = (rel) => /\.tsx?$/.test(rel) && !rel.endsWith(".d.ts");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/**
 * Every module specifier a file pulls in: static imports, re-exports and
 * dynamic `import()`. Bare package names and asset imports fall out in
 * resolve() — matching them here would mean duplicating the resolver.
 */
const SPECIFIER_RE =
  /(?:^|[^\w$])(?:import|export)\s[^;'"]*?from\s*["']([^"']+)["']|(?:^|[^\w$])import\s*["']([^"']+)["']|\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;

export function specifiersOf(text) {
  const found = new Set();
  for (const match of text.matchAll(SPECIFIER_RE)) {
    found.add(match[1] ?? match[2] ?? match[3]);
  }
  return found;
}

const CANDIDATE_SUFFIXES = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"];

/** Resolve a specifier to a src-relative path, or null when it leaves src. */
export function resolveSpecifier(spec, fromRel, known) {
  let base;
  if (spec.startsWith("@/")) base = spec.slice(2);
  else if (spec.startsWith("."))
    base = relative(SRC, resolve(SRC, dirname(fromRel), spec));
  else return null; // node_modules
  if (base.startsWith("..")) return null; // outside src/
  for (const suffix of CANDIDATE_SUFFIXES) {
    const candidate = base + suffix;
    if (known.has(candidate)) return candidate;
  }
  return null;
}

const isRoot = (rel) =>
  ROOT_PATTERNS.some((p) => (typeof p === "string" ? p === rel : p.test(rel)));

/**
 * Walk the import graph and return every source file no root can reach.
 * Exported so the spec can drive it over a fixture graph instead of src/.
 */
export function unreachableFrom(files, readFile) {
  const known = new Set(files);
  // importers.get(x) = every file importing x, spec or not — the reverse
  // edges are what separates "nothing imports it" from "only its spec does".
  const importers = new Map(files.map((f) => [f, new Set()]));
  const imports = new Map();
  for (const rel of files) {
    const targets = new Set();
    for (const spec of specifiersOf(readFile(rel))) {
      const target = resolveSpecifier(spec, rel, known);
      if (target && target !== rel) {
        targets.add(target);
        importers.get(target).add(rel);
      }
    }
    imports.set(rel, targets);
  }

  const roots = files.filter(isRoot);
  const reachable = new Set();
  const queue = [...roots];
  while (queue.length > 0) {
    const current = queue.pop();
    if (reachable.has(current)) continue;
    reachable.add(current);
    for (const target of imports.get(current) ?? []) queue.push(target);
  }

  const findings = files
    .filter(
      (rel) =>
        !reachable.has(rel) &&
        !isSpec(rel) &&
        !EXEMPT.includes(rel) &&
        !isRoot(rel),
    )
    .map((rel) => {
      const all = [...importers.get(rel)];
      return {
        file: rel,
        testOnly: all.length > 0 && all.every(isSpec),
        importers: all.length,
      };
    })
    // Plain codepoint order, not localeCompare: the report and the
    // baseline must read the same on every host and inside the container.
    .sort((a, b) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0));

  return { findings, roots };
}

const describe = (f) =>
  f.testOnly
    ? `${f.file}  (reachable only from its own spec)`
    : f.importers === 0
      ? `${f.file}  (nothing imports it)`
      : `${f.file}  (imported, but the chain never reaches a production root)`;

const report = (label, list, log) => {
  log(`${label} (${list.length}):`);
  for (const f of list) log(`  - ${describe(f)}`);
};

function main() {
  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isSource);
  const { findings, roots } = unreachableFrom(files, (rel) =>
    readFileSync(resolve(SRC, rel), "utf8"),
  );
  const args = process.argv.slice(2);

  if (args.includes("--write-baseline")) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          unreachable: findings.map((f) => f.file),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `reachability baseline written: ${findings.length} finding(s) → scripts/reachability-baseline.json`,
    );
    process.exit(0);
  }

  if (args.includes("--baseline")) {
    const baseline = existsSync(BASELINE_PATH)
      ? new Set(JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unreachable)
      : new Set();
    const fresh = findings.filter((f) => !baseline.has(f.file));
    if (fresh.length > 0) {
      report(
        "reachability regression — NEW unreachable file(s)",
        fresh,
        console.error,
      );
      console.error(
        "\nWire the file into a production path or delete it (with its spec). " +
          "Do NOT grandfather it into the baseline.",
      );
      process.exit(1);
    }
    const fixed = [...baseline].filter(
      (b) => !findings.some((f) => f.file === b),
    );
    console.log(
      fixed.length > 0
        ? `reachability passed baseline: ${findings.length} known finding(s), ${fixed.length} fixed since baseline. Run --write-baseline to refresh.`
        : `reachability passed baseline: ${findings.length} known finding(s).`,
    );
    process.exit(0);
  }

  console.log(
    `Scanned ${files.length} file(s) from ${roots.length} production root(s).`,
  );
  if (findings.length === 0) {
    console.log(
      "reachability: every source file is reachable from a production root.",
    );
    process.exit(0);
  }
  report("Unreachable from any production root", findings, console.error);
  process.exit(1);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
