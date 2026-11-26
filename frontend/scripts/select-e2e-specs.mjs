#!/usr/bin/env node
/**
 * select-e2e-specs.mjs
 *
 * The browser suite takes too long to run for every merge and no local gate
 * runs it, so this picks, from a diff, the specs that diff can break:
 *
 *  - a spec the diff changes,
 *  - a spec that imports, directly or through a helper, a changed file, or
 *    reads a changed data file of the E2E tree,
 *  - a spec that spells a catalog text the diff removed (the matcher of
 *    `check-e2e-catalog-text.mjs`),
 *  - for a changed `frontend/src/modules/<m>/` or `backend/app/modules/<m>/`:
 *    the specs named after the module and those that open one of the routes its
 *    `module.ts` declares. Tests, documents and translations select nothing
 *    here; a changed text is the catalog matcher's.
 *
 * A change to what every screen stands on (the Playwright config, the shared
 * fixture and global setup, the router, the app shell) selects the full suite.
 *
 *   node frontend/scripts/select-e2e-specs.mjs [--base <ref>] [--run]
 *
 * The spec paths, relative to `frontend/`, go to stdout, one per line, and the
 * reason for each to stderr. The range is the merge base of `--base` (default
 * `origin/dev`) and HEAD to the working tree. Runs on the host: it needs git.
 *
 * `--run` runs the selection with Playwright against the stack `VITE_API_URL`
 * names, project by project in dependency order and with `--no-deps`: naming a
 * file otherwise runs every project it depends on in full. Every phase runs
 * even after a red one.
 *
 * Exit 1 when a run is red, 2 when the base cannot be read.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, posix, resolve } from "node:path";

import {
  literals,
  staleTextSince,
  unescaped,
} from "./check-e2e-catalog-text.mjs";
import { blankComments } from "./source-text.mjs";

const ROOT = resolve(import.meta.dirname, ".."); // frontend/

/** What every screen or every spec stands on: a change selects the suite. */
const SHARED_SHELL = [
  /^frontend\/playwright\.config\.ts$/,
  /^frontend\/tests\/e2e\/(?:fixtures\/base|globalSetup|globalTeardown)\.ts$/,
  /^frontend\/src\/(?:(?:App|Root|PublicApp|main)\.tsx|publicRoutes\.ts)$/,
  /^frontend\/src\/lib\/moduleRegistry(?:\.ts|\/[^./]+\.tsx?)$/,
  /^frontend\/src\/components\/(?:(?:AppShell|ModuleShell)|shell\/[^./]+)\.tsx?$/,
];

const MODULE_FILE =
  /^(?:frontend\/src|backend\/app)\/modules\/([^/]+)\/(?!(?:.*\/)?(?:__tests__|tests|i18n)\/)(?!.*(?:\.test\.|\.md$))/;

/**
 * Playwright's projects in an order that respects their dependencies; one entry
 * is one invocation. A spec checks this against `playwright.config.ts`.
 */
export const PHASES = [
  ["chromium", "mobile", "pl-PL"],
  ["module-gate"],
  ["approvals"],
  ["approvals-mobile"],
  ["value-tracking"],
  ["announcements"],
  ["org-profile"],
];

/** The route paths a `module.ts` declares, as expressions matching one whole. */
function routePatterns(source) {
  return [...blankComments(source).matchAll(/\bpath:\s*["'](\/[^"']+)["']/g)]
    .map(([, path]) =>
      path
        .split("/")
        .map((part) =>
          part.startsWith(":")
            ? "[^/?#]+"
            : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
        )
        .join("/"),
    )
    .map((path) => new RegExp(`^${path}/?(?=$|[?#$)])`));
}

const IMPORT = /(?:\bfrom|\bimport)\s*\(?\s*["'](\.[^"']*)["']/g;

/**
 * The specs a diff can break, `{ full, specs: Map<spec, reasons[]> }`; `full`
 * names the files that selected the whole suite.
 *
 * @param changed  paths the diff touches, relative to the repository
 * @param specs    every spec, relative to `frontend/`
 * @param read     the source of a path relative to `frontend/`, or null
 * @param stale    findings of the catalog matcher, `[{ spec, old }]`
 */
export function selectSpecs({ changed, specs, read, stale = [] }) {
  const full = changed.filter((path) =>
    SHARED_SHELL.some((pattern) => pattern.test(path)),
  );
  const selected = new Map();
  const select = (spec, reason) => {
    const reasons = selected.get(spec) ?? [];
    if (!reasons.includes(reason)) selected.set(spec, [...reasons, reason]);
  };

  const diff = new Set(
    changed
      .filter((path) => path.startsWith("frontend/"))
      .map((path) => path.slice("frontend/".length)),
  );
  const data = [...diff].filter(
    (path) => path.startsWith("tests/e2e/") && !/\.(?:tsx?|md)$/.test(path),
  );
  const modules = new Set(
    changed.map((path) => path.match(MODULE_FILE)?.[1]).filter(Boolean),
  );
  const routes = [...modules].map((module) => ({
    module,
    name: new RegExp(
      `/${module.replaceAll("_", "-")}(?:-[^/]*)?\\.spec\\.ts$`,
    ),
    patterns: routePatterns(read(`src/modules/${module}/module.ts`) ?? ""),
  }));

  for (const spec of specs) {
    if (diff.has(spec)) select(spec, "changed");
    // The spec and everything it imports, transitively.
    const closure = new Set([spec]);
    for (const file of closure) {
      const source = read(file);
      if (source === null) continue;
      for (const [, target] of blankComments(source).matchAll(IMPORT)) {
        const path = posix.join(posix.dirname(file), target);
        const found = ["", ".ts", ".tsx", "/index.ts"]
          .map((end) => path + end)
          .find((candidate) => diff.has(candidate) || read(candidate) !== null);
        if (found) closure.add(found);
      }
      for (const path of data)
        if (source.includes(basename(path))) select(spec, `reads ${path}`);
    }
    for (const file of closure)
      if (file !== spec && diff.has(file)) select(spec, `imports ${file}`);
    for (const finding of stale)
      if (closure.has(finding.spec))
        select(spec, `spells removed text ${JSON.stringify(finding.old)}`);

    if (routes.length === 0) continue;
    const opened = literals(read(spec) ?? "").map((literal) =>
      unescaped(literal.text).replace(/^\^/, "").trim(),
    );
    for (const { module, name, patterns } of routes) {
      if (name.test(spec)) select(spec, `module ${module}: named after it`);
      else if (
        opened.some((text) => patterns.some((pattern) => pattern.test(text)))
      )
        select(spec, `module ${module}: opens its route`);
    }
  }

  if (full.length > 0)
    for (const spec of specs) select(spec, "full suite");
  return { full, specs: selected };
}

function git(...args) {
  return execFileSync("git", args, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function read(path) {
  const file = join(ROOT, path);
  return existsSync(file) && statSync(file).isFile()
    ? readFileSync(file, "utf8")
    : null;
}

function playwright(args, options) {
  return spawnSync("npx", ["playwright", "test", ...args], {
    cwd: ROOT,
    ...options,
  });
}

/** The exit code of the selected specs' run. */
function run(files, full) {
  // The suite whole is the config's own business: its order and its projects.
  if (full) return playwright(["--reporter=list"], { stdio: "inherit" }).status;
  const listing = playwright(
    ["--list", "--no-deps", "--pass-with-no-tests", ...files],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  if (listing.status !== 0) {
    console.error(`${listing.stdout}${listing.stderr}`);
    return 1;
  }
  const listed = new Set(
    [...listing.stdout.matchAll(/^\s*\[([^\]]+)\] ›/gm)].map(([, name]) => name),
  );
  const red = [];
  for (const phase of PHASES) {
    const projects = phase.filter((project) => listed.has(project));
    if (projects.length === 0) continue;
    const { status } = playwright(
      [
        ...projects.map((project) => `--project=${project}`),
        "--no-deps",
        "--pass-with-no-tests",
        "--reporter=list",
        // One directory per phase: a run empties its own before it starts.
        `--output=test-results/${projects[0]}`,
        ...files,
      ],
      { stdio: "inherit" },
    );
    if (status !== 0) red.push(...projects);
  }
  if (red.length === 0) return 0;
  console.error(`e2e selection: red in ${red.join(", ")}.`);
  return 1;
}

/** The exit code of one run. */
function main(argv) {
  const flag = argv.indexOf("--base");
  const base = flag === -1 ? "origin/dev" : argv[flag + 1];
  let changed;
  let stale;
  try {
    const from = git("merge-base", base, "HEAD").trim();
    changed = git("diff", "--name-only", "--no-renames", from)
      .split("\n")
      .filter(Boolean);
    stale = staleTextSince(base);
  } catch (error) {
    console.error(
      `e2e selection: cannot read the changes since ${base}: ${error.stderr?.trim() || error.message}\nFetch it, or name another base with --base <ref>.`,
    );
    return 2;
  }

  const specs = readdirSync(join(ROOT, "tests/e2e"), { recursive: true })
    .filter((path) => path.endsWith(".spec.ts"))
    .map((path) => `tests/e2e/${path}`)
    .sort();
  const selection = selectSpecs({ changed, specs, read, stale });
  const files = [...selection.specs.keys()];
  const full = selection.full.length > 0;

  console.error(
    `e2e selection since ${base}: ${files.length} of ${specs.length} specs${full ? `, the full suite (${selection.full.join(", ")})` : ""}.`,
  );
  if (!full)
    for (const [spec, reasons] of selection.specs)
      console.error(`  ${spec}: ${reasons.join("; ")}`);
  for (const file of files) console.log(file);

  if (!argv.includes("--run") || files.length === 0) return 0;
  return run(files, full);
}

if (process.argv[1] && resolve(process.argv[1]) === import.meta.filename) {
  process.exitCode = main(process.argv.slice(2));
}
