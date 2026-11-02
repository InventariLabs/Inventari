#!/usr/bin/env node
/**
 * check-focus-reachability.mjs
 *
 * Single-module focus mode hides every module but the chosen one from the
 * navigation — but the hidden modules' routes STAY MOUNTED. The static
 * reachability gates (check-route-reachability, check-reachability) read
 * App.tsx and the module.ts files and cannot see runtime hiding, so a route
 * can be mounted, linked, and still unreachable for an organization that hid
 * its owner. The classic case: /inventory/labels (the label pool) and
 * /labels/scan/:code (the one entry a printed QR sticker has) once inventory
 * is hidden — a sticker that stops scanning is a broken physical artifact,
 * not a UI glitch.
 *
 * What makes this checkable at all is the `standalone` declaration: a module
 * that may serve as the single focus module must account for every adoptable
 * core section ("adopt" / "renounce", enforced by standaloneGate.test.ts)
 * and name the core nav sections it keeps (`keepCoreNav`). This gate recomputes
 * reachability from that DECLARED configuration, per standalone module:
 *
 *   adopted     — route under a section the module adopts: the shell renders
 *                 it under the module's banner. Accounted for.
 *   renounced   — under a section the module renounces: declared
 *                 unreachable-on-purpose. Accounted for.
 *   kept        — under a keepCoreNav section that stays visible. Accounted.
 *   core-list   — under a core nav section the module did NOT keep: hidden by
 *                 the module's own declaration (an empty keepCoreNav is a
 *                 declared choice, not an oversight). Accounted.
 *   base        — the owner module's own basePath route (/inventory): hiding
 *                 the module's dashboard IS the act of focus. Accounted.
 *   UNACCOUNTED — anything else: a mounted core route no declaration covers.
 *                 This is the finding. It names the route, the owner module
 *                 whose hiding orphaned it, and the focus module that failed
 *                 to account for it.
 *
 * Drift is checked both ways: a prefix in CORE_SECTION_PATH_PREFIXES (or in
 * KEEPABLE_CORE_NAV_PATHS below) that no mounted route matches is a dead
 * claim — an adoption pointing at a deleted route — and is reported too.
 *
 * Scope is the routes focus-mode hiding can orphan: the routes of the core
 * modules that own the adoptable sections (SECTION_OWNERS below) plus static
 * App.tsx routes under /inventory or /labels. The owner set is hardcoded on
 * purpose: adding a new core surface that focus mode could orphan is the
 * deliberate act of extending it — the same philosophy as standaloneGate's
 * ADOPTABLE_CORE_SECTIONS. Optional modules (recipes, maker, …) hidden in
 * focus mode are out of scope: hiding them is the point of the mode and the
 * command palette still reaches them — the single-module-mode decision on
 * optional modules is exactly that: they stay reachable outside the
 * navigation, so flagging them would be noise.
 *
 * Modes:
 *   node check-focus-reachability.mjs                 # full report, exit 1
 *   node check-focus-reachability.mjs --baseline      # only NEW findings fail
 *   node check-focus-reachability.mjs --write-baseline  # snapshot current
 *
 * Baseline: frontend/scripts/focus-reachability-baseline.json
 * The goal is an EMPTY baseline — account for the route in the module's
 * standalone declaration (or remove the route), don't grandfather it.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const APP_TSX = resolve(SRC, "App.tsx");
const CORE_SECTIONS_TS = resolve(SRC, "lib/moduleRegistry/coreSections.ts");
const BASELINE_PATH = resolve(ROOT, "scripts/focus-reachability-baseline.json");

// The core modules whose routes focus-mode hiding can orphan — the owners of
// the adoptable sections. inventory carries the /inventory/* sections;
// spaces, stock_takes and stats host their sections in the inventory shell
// (`ModuleRoute.shell`); printing owns the flat /labels/scan/:code a physical
// QR sticker references.
const SECTION_OWNERS = ["inventory", "spaces", "stock_takes", "stats", "printing"];

// Where each keepable core nav section lives in the route tree — the path map
// for CoreNavSection ("items" | "storages" | "categories" | "stock" | "moves")
// from moduleInterfaces.ts. It lives here, not in src/, because the shell
// reads keepCoreNav as section names against inventory's moduleNav items and
// never needs the route prefixes; this gate does. Keep it next to the
// classification that depends on it, and match longest-prefix-first so
// /inventory/stock-takes never falls into `stock`.
const KEEPABLE_CORE_NAV_PATHS = {
  items: ["/inventory/items"],
  storages: ["/inventory/locations"],
  categories: ["/inventory/categories"],
  stock: ["/inventory/stock", "/inventory/lots"],
  moves: ["/inventory/moves"],
};

// ---------------------------------------------------------------------------
// Parsing helpers — copied from check-route-reachability.mjs. These are
// single-file scripts with nothing exported between them; a copied 10-line
// brace counter beats inventing a shared package for two gates.
// ---------------------------------------------------------------------------

/**
 * Contents of a `key: [ ... ]` / `key: { ... }` literal in a module file.
 * Brace counting rather than a parser: module.ts files are prettier-formatted
 * registration calls, and importing them would need a DOM, i18n and every
 * icon package the modules pull in.
 */
export function sliceBlock(text, key) {
  const start = text.search(new RegExp(`^\\s*${key}:\\s*[[{]`, "m"));
  if (start === -1) return null;
  return sliceFrom(text, start + text.slice(start).search(/[[{]/));
}

/**
 * Contents of an `export const NAME ... = { ... }` / `[ ... ]` literal.
 * Unlike sliceBlock the value is not directly after the key (a type
 * annotation sits in between), so the opening brace is the first one after
 * the name.
 */
export function sliceConst(text, name) {
  const start = text.search(new RegExp(`\\b${name}\\b`));
  if (start === -1) return null;
  // Anchor on the `=`, not the name: the type annotation in between may
  // itself hold brackets (`Record<AdoptableCoreSection, string[]>`).
  const eqAt = text.slice(start).search(/=/);
  if (eqAt === -1) return null;
  const braceAt = text.slice(start + eqAt).search(/[[{]/);
  if (braceAt === -1) return null;
  return sliceFrom(text, start + eqAt + braceAt);
}

function sliceFrom(text, braceStart) {
  const open = text[braceStart];
  const close = open === "[" ? "]" : "}";
  let depth = 0;
  for (let i = braceStart; i < text.length; i++) {
    const ch = text[i];
    // Skip comments first: coreSections.ts documents its entries with `//`
    // lines, and a lone backtick or apostrophe inside a comment (printing's,
    // `/labels/scan/:code`) would otherwise be read as a string opener and
    // swallow the rest of the file.
    if (ch === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      continue;
    }
    if (ch === "/" && text[i + 1] === "*") {
      i += 2;
      while (i < text.length && !(text[i] === "*" && text[i + 1] === "/")) i++;
      i++;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      // Skip the string body: a template literal can contain `${...}` braces
      // that would unbalance the count.
      const quote = ch;
      i++;
      while (i < text.length && text[i] !== quote) {
        if (text[i] === "\\") i++;
        i++;
      }
      continue;
    }
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return text.slice(braceStart + 1, i);
    }
  }
  return null;
}

/** All `path: "..."` values in a block, in source order. */
export function pathsIn(block) {
  return [...block.matchAll(/\bpath:\s*"([^"]*)"/g)].map((m) => m[1]);
}

/** All quoted strings in a block — a `section: ["/a", "/b"]` entry's value. */
function stringsIn(block) {
  return [...block.matchAll(/"([^"]*)"/g)].map((m) => m[1]);
}

// ---------------------------------------------------------------------------
// Declaration extraction
// ---------------------------------------------------------------------------

/**
 * `CORE_SECTION_PATH_PREFIXES` from coreSections.ts, as
 * { section: [prefix, ...] }. Parsed, not imported: the module pulls in
 * lucide-react, and a gate that needs a bundler to read a map is a gate that
 * stops running the day an import breaks.
 */
export function parseCoreSectionPrefixes(text) {
  const block = sliceConst(text, "CORE_SECTION_PATH_PREFIXES");
  const out = {};
  if (!block) return out;
  for (const m of block.matchAll(/(\w+):\s*\[([^\]]*)\]/g)) {
    out[m[1]] = stringsIn(m[2]);
  }
  return out;
}

/**
 * A module's `standalone` declaration, or null when the module does not
 * declare one (most modules — only a focus candidate does).
 * Returns { coreSections: { section: "adopt"|"renounce" }, keepCoreNav: [] }.
 */
export function parseStandalone(text) {
  const block = sliceBlock(text, "standalone");
  if (!block) return null;
  const coreSections = {};
  const sectionsBlock = sliceBlock(block, "coreSections");
  if (sectionsBlock) {
    for (const m of sectionsBlock.matchAll(/(\w+):\s*"(adopt|renounce)"/g)) {
      coreSections[m[1]] = m[2];
    }
  }
  const keepBlock = sliceBlock(block, "keepCoreNav");
  return { coreSections, keepCoreNav: keepBlock ? stringsIn(keepBlock) : [] };
}

function moduleFiles() {
  const dir = join(SRC, "modules");
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    for (const name of ["module.ts", "module.tsx"]) {
      const full = join(dir, entry.name, name);
      if (existsSync(full)) files.push([entry.name, full]);
    }
  }
  return files;
}

// ---------------------------------------------------------------------------
// Scope: the routes hiding can orphan
// ---------------------------------------------------------------------------

/**
 * The routes one owner module contributes, plus its basePath. Index entries
 * render AT the base path; the base path itself comes from moduleNav and is
 * classified on its own (`base`).
 */
function readOwnerRoutes(name) {
  const file = ["module.ts", "module.tsx"]
    .map((f) => join(SRC, "modules", name, f))
    .find((f) => existsSync(f));
  if (!file) return [];
  const text = readFileSync(file, "utf8");

  const navBlock = sliceBlock(text, "moduleNav");
  const basePath = navBlock
    ? (navBlock.match(/\bbasePath:\s*"([^"]*)"/)?.[1] ?? "").replace(/\/$/, "")
    : null;

  const routes = [];
  const routesBlock = sliceBlock(text, "routes");
  if (routesBlock) {
    for (const entry of routesBlock.split(/\},?\s*(?=\{)/)) {
      if (/\bindex:\s*true/.test(entry)) continue;
      for (const p of pathsIn(entry)) {
        if (!p.startsWith("/")) continue; // relative: mounted under a base
        routes.push({ path: p, owner: name });
      }
    }
  }
  if (basePath) routes.push({ path: basePath, owner: name, isBase: true });
  return routes;
}

/**
 * Static App.tsx routes under /inventory or /labels. Redirect aliases are
 * skipped: a `<Navigate>` / `RedirectPreserving` route forwards to the real
 * route, which is classified on its own — flagging the forwarding address
 * would double-report the destination. (Today the only static route in these
 * trees is exactly such an alias: /labels → /inventory/labels.)
 */
function readAppStaticRoutes() {
  const lines = readFileSync(APP_TSX, "utf8").split(/\r?\n/);
  const routes = [];
  const stack = []; // absolute path contexts
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes("</Route>")) {
      stack.pop();
      continue;
    }
    if (!lines[i].includes("<Route")) continue;

    // Same tag-span scan as check-route-reachability's extractRoutes:
    // prettier puts the closing `>`/`/>` of the ROUTE tag at the same
    // indentation as `<Route`.
    let path = null;
    let isRedirect = false;
    const indent = lines[i].match(/^\s*/)[0].length;
    let selfClosing = false;
    for (let j = i; j < lines.length; j++) {
      const trimmed = lines[j].trimEnd();
      const atTagLevel = lines[j].match(/^\s*/)[0].length === indent;
      if (atTagLevel && trimmed.endsWith("/>")) selfClosing = true;
      const m = path == null ? lines[j].match(/path="([^"]+)"/) : null;
      if (m) path = m[1];
      if (/<(Navigate|RedirectPreserving)\b/.test(lines[j])) isRedirect = true;
      if (atTagLevel && (trimmed.endsWith("/>") || trimmed.endsWith(">")))
        break;
    }
    if (path == null || path === "index" || path === "*") continue;
    const resolved = path.startsWith("/")
      ? path
      : `${stack[stack.length - 1] ?? ""}/${path}`;
    if (!selfClosing) stack.push(resolved);
    if (isRedirect) continue;
    if (
      resolved === "/inventory" ||
      resolved === "/labels" ||
      resolved.startsWith("/inventory/") ||
      resolved.startsWith("/labels/")
    ) {
      routes.push({ path: resolved, owner: "App.tsx" });
    }
  }
  return routes;
}

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

/**
 * Every prefix a classification can come from, longest first, so a more
 * specific path always wins over a shallower one that happens to prefix it
 * (/inventory/stock-takes is `stock_takes`, never `stock`). `kind` says which
 * map the prefix came from: an adoptable section ("section") or a keepable
 * core nav section ("coreNav").
 */
export function buildPrefixTable(sectionPrefixes) {
  const entries = [];
  for (const [section, prefixes] of Object.entries(sectionPrefixes)) {
    for (const prefix of prefixes)
      entries.push({ prefix, kind: "section", section });
  }
  for (const [section, prefixes] of Object.entries(KEEPABLE_CORE_NAV_PATHS)) {
    for (const prefix of prefixes)
      entries.push({ prefix, kind: "coreNav", section });
  }
  return entries.sort((a, b) => b.prefix.length - a.prefix.length);
}

/**
 * First table entry whose prefix covers the route, on a segment boundary —
 * without the boundary /inventory/stock would swallow a hypothetical
 * /inventory/stockade.
 */
export function matchPrefix(route, table) {
  for (const entry of table) {
    if (route === entry.prefix || route.startsWith(entry.prefix + "/")) {
      return entry;
    }
  }
  return null;
}

/**
 * Where one in-scope route stands under one focus module's declaration.
 * See the header for the meaning of each status.
 */
export function classifyRoute(route, { basePath, focus, table }) {
  if (basePath && route === basePath) return { status: "base" };
  const m = matchPrefix(route, table);
  if (!m) return { status: "unaccounted" };
  if (m.kind === "section") {
    const declared = focus.coreSections[m.section];
    // A missing entry means standaloneGate was bypassed — a declaration hole
    // is still a hole, so it lands in unaccounted rather than being trusted.
    if (declared === "adopt") return { status: "adopted", section: m.section };
    if (declared === "renounce")
      return { status: "renounced", section: m.section };
    return { status: "unaccounted", section: m.section };
  }
  return {
    status: focus.keepCoreNav.includes(m.section) ? "kept" : "core-list",
    section: m.section,
  };
}

/**
 * Classify every in-scope route against every focus module, plus the drift
 * check: a prefix no mounted route matches is a dead claim (an adoption
 * pointing at a deleted route) and is reported as map drift.
 *
 * scopeRoutes: [{ path, owner, isBase? }]; focusModules:
 * [{ name, coreSections, keepCoreNav }]. Returns
 * { perModule: Map<name, counts>, findings: [...] }.
 */
export function collectFindings(scopeRoutes, focusModules, table) {
  const perModule = new Map();
  const findings = [];

  for (const focus of focusModules) {
    const counts = {
      adopted: 0,
      renounced: 0,
      kept: 0,
      "core-list": 0,
      base: 0,
      unaccounted: 0,
    };
    for (const route of scopeRoutes) {
      const basePath = route.isBase ? route.path : null;
      const { status, section } = classifyRoute(route.path, {
        basePath,
        focus,
        table,
      });
      counts[status]++;
      if (status === "unaccounted") {
        findings.push({
          kind: "unaccounted",
          route: route.path,
          owner: route.owner,
          focus: focus.name,
          section: section ?? null,
        });
      }
    }
    perModule.set(focus.name, counts);
  }

  for (const entry of table) {
    const mounted = scopeRoutes.some(
      (r) => matchPrefix(r.path, [entry]) != null,
    );
    if (!mounted) {
      findings.push({
        kind: "map-drift",
        prefix: entry.prefix,
        section: entry.section,
        map: entry.kind,
      });
    }
  }

  return { perModule, findings };
}

/** The stable, readable key baseline comparison runs on. */
export function findingKey(f) {
  if (f.kind === "map-drift") {
    return `map drift: "${f.prefix}" (${f.map}: ${f.section}) matches no mounted route`;
  }
  return `${f.route}  [owner: ${f.owner}, focus: ${f.focus}]`;
}

/**
 * Split current findings against the baseline: only findings NOT in the
 * baseline fail the gate; baseline entries that no longer occur are reported
 * as fixed so the snapshot gets refreshed.
 */
export function diffBaseline(findings, baselineKeys) {
  const baseline = new Set(baselineKeys);
  return {
    newFindings: findings.filter((f) => !baseline.has(findingKey(f))),
    fixed: [...baseline].filter(
      (key) => !findings.some((f) => findingKey(f) === key),
    ),
  };
}

// ---------------------------------------------------------------------------
// Main
//
// Guarded so the module can be imported by its test without the CLI running
// (and calling process.exit) as a side effect of the import.
// ---------------------------------------------------------------------------

function main() {
  const args = process.argv.slice(2);
  const useBaseline = args.includes("--baseline");
  const writeBaseline = args.includes("--write-baseline");

  const sectionPrefixes = parseCoreSectionPrefixes(
    readFileSync(CORE_SECTIONS_TS, "utf8"),
  );
  const table = buildPrefixTable(sectionPrefixes);

  const scopeRoutes = [];
  const seen = new Set();
  for (const owner of SECTION_OWNERS) {
    for (const r of readOwnerRoutes(owner)) {
      if (seen.has(r.path)) continue;
      seen.add(r.path);
      scopeRoutes.push(r);
    }
  }
  for (const r of readAppStaticRoutes()) {
    if (seen.has(r.path)) continue;
    seen.add(r.path);
    scopeRoutes.push(r);
  }
  scopeRoutes.sort((a, b) => a.path.localeCompare(b.path));

  const focusModules = [];
  for (const [name, file] of moduleFiles()) {
    const standalone = parseStandalone(readFileSync(file, "utf8"));
    if (standalone) focusModules.push({ name, ...standalone });
  }

  const { perModule, findings } = collectFindings(
    scopeRoutes,
    focusModules,
    table,
  );

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          unaccounted: findings.map(findingKey),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `focus-reachability baseline written: ${findings.length} finding(s) → scripts/focus-reachability-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unaccounted
      : [];
  const { newFindings, fixed } = diffBaseline(findings, baseline);

  console.log(
    `focus-reachability: ${scopeRoutes.length} in-scope core route(s), ` +
      `${focusModules.length} standalone focus module(s), ` +
      `${findings.length} finding(s)`,
  );
  for (const [name, counts] of perModule) {
    console.log(
      `\nfocus module: ${name}\n` +
        `  adopted: ${counts.adopted}  renounced: ${counts.renounced}  ` +
        `kept: ${counts.kept}  hidden (core-list): ${counts["core-list"]}  ` +
        `base: ${counts.base}`,
    );
  }

  if (newFindings.length > 0) {
    const unaccounted = newFindings.filter((f) => f.kind === "unaccounted");
    const drift = newFindings.filter((f) => f.kind === "map-drift");
    if (unaccounted.length > 0) {
      console.error(
        `\n✗ NEW unaccounted core route(s) under focus mode (${unaccounted.length}):`,
      );
      for (const f of unaccounted)
        console.error(`  - ${f.route}  [owner: ${f.owner}, focus: ${f.focus}]`);
    }
    if (drift.length > 0) {
      console.error(`\n✗ NEW map drift (${drift.length}):`);
      for (const f of drift)
        console.error(
          `  - prefix "${f.prefix}" (${f.map}: ${f.section}) matches no mounted route`,
        );
    }
    console.error(
      "\nAccount for the route in the focus module's `standalone` declaration" +
        " (adopt or renounce the section, or keep the core nav section)," +
        " remove the dead route, or fix the drifted prefix map.",
    );
    process.exit(1);
  }
  if (fixed.length > 0) {
    console.log(
      `\n✓ no new findings (${fixed.length} baseline finding(s) resolved — run --write-baseline to refresh).`,
    );
  } else {
    console.log(
      "\n✓ no unaccounted core routes under any declared focus module",
    );
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
