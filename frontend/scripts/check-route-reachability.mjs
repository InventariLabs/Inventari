#!/usr/bin/env node
/**
 * check-route-reachability.mjs
 *
 * Detects routes that no UI entry point references — routes declared
 * statically in src/App.tsx AND routes contributed by modules
 * (each module.ts `routes` array). A route with no `to` /
 * `navigate` / `href` / nav item pointing at it is either orphaned after a
 * refactor (the SettingsPage.tsx bug class) or reachable only by typing the
 * URL.
 *
 * Module routes used to be exempt on the grounds that App.tsx renders them
 * dynamically, so they are "reachable by construction". That confuses
 * MOUNTED with REACHABLE: /warehouse/periods was mounted for months with
 * nothing in the UI leading to it (since fixed by adding a nav entry).
 * Mounting is what makes a route resolve; a link is what makes a person
 * arrive. This gate is about the second one.
 *
 * To this gate a parameterized route is one route, and one reference to
 * any instance covers the pattern. For the settings route that was not
 * enough — `/settings/modules/webhooks` satisfied `/settings/modules/:name` while
 * four other modules declared a settings schema and nothing linked to
 * theirs. The parameterized settings route is therefore checked per
 * instance below: every backend module declaring a settings schema needs
 * a reference naming its own instance, or a settings screen of its own
 * inside the module. Every other parameterized route keeps the
 * one-reference-covers-the-pattern reading.
 *
 * How it works:
 *   1. Parses src/App.tsx for `<Route path="...">` and resolves nesting
 *      (settings → settings/workspace) with a line-based context stack.
 *      App.tsx is a single, stable-format file — regex is sufficient.
 *   2. Parses each module's module.ts for the `routes` it contributes.
 *      Index routes are skipped — they render at the module's base path,
 *      which is checked in its own right. `settingsSections` are skipped
 *      too, and the reason is at the call site in readModules().
 *   3. Collects references across src/** (tests excluded): `to="/x"`,
 *      `to: "/x"` (data objects), `navigate("/x")`, `href="/x"`,
 *      `linkTo: "/x"` (launcher action items), and template-literal variants.
 *      Module nav items count too: `moduleNav.items[].path` resolved against
 *      `basePath`, plus each module's launcher tile target (the same
 *      `launcher.linkTo ?? moduleNav.basePath ?? routes[0].path` chain
 *      `resolveModuleTarget` uses). These are references the regexes cannot
 *      see, because the link is built by the shell from registry data.
 *   4. A route is OK when a reference matches it, or it is listed in
 *      DEEPLINK_ALLOWLIST below (external entry points — email links,
 *      redirect aliases kept for backward compatibility).
 *
 * Modes:
 *   node check-route-reachability.mjs                # full report, exit 1
 *   node check-route-reachability.mjs --baseline     # only NEW unreachable fail
 *   node check-route-reachability.mjs --write-baseline  # snapshot current
 *
 * Baseline: frontend/scripts/route-reachability-baseline.json
 * The goal is an EMPTY baseline — add nav entries or remove dead routes,
 * don't grandfather them.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

// fileURLToPath, not `new URL(.., import.meta.url).pathname`: vitest's jsdom
// environment swaps in a URL polyfill whose constructor chokes on the
// module runner's import.meta.url, and the script's own test would then
// resolve ROOT to nowhere.
const ROOT = resolve(fileURLToPath(import.meta.url), "..", ".."); // frontend/
const SRC = resolve(ROOT, "src");
const APP_TSX = resolve(SRC, "App.tsx");
const BASELINE_PATH = resolve(ROOT, "scripts/route-reachability-baseline.json");

// ---------------------------------------------------------------------------
// Deeplink allowlist — routes intentionally reachable OUTSIDE the UI
// (external links, bookmarks, redirect aliases). Each entry gets a comment
// explaining WHY it must stay without an in-app reference.
// ---------------------------------------------------------------------------
const DEEPLINK_ALLOWLIST = [
  // Auth pages — reached via redirects, email links and external bookmarks.
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password/:token", // password-reset email link (backend sends it)
  "/join", // organization invite email link
  "/join/:token", // same invite link, older links carry the code in the path
  "/onboarding", // post-registration flow (redirected to, never linked)
  "/public/attestation/:token", // public attestation link shared externally
  // The address a printed QR opens (backend scan_links.scan_url): reached
  // from a phone camera reading a label, never from a link in the app.
  "/s/*",
  // Stable launcher URL — no in-app link by design.
  "/launcher",
  // Backward-compatibility redirect aliases (old paths → new module homes).
  // Referenced by old bookmarks/external links; intentionally kept.
  "/warehouse",
  "/items",
  "/items/add",
  "/items/:id",
  "/categories",
  "/scan",
  "/storages",
  "/storages/:id",
  "/labels",
  "/stats",
  "/stats/inventory",
  "/stats/analytics",
  "/stock-takes",
  "/stock-takes/:id/counting",
  // The webhooks screen lives at /settings/webhooks; this flat path was a
  // second, header-less copy of it and now only redirects.
  "/webhooks",
  // "Developer" held the mail server and the AI connections under a name that
  // described neither; both now have their own entries. The old address stays
  // so a bookmark lands somewhere.
  "/settings/developer",
  // The whole content of this page was a sentence and a button pointing at
  // apps, which is also where the sidebar links. Now a redirect.
  "/settings/modules",
  // "My modules" holds the module set and the show-only-one toggles on one
  // screen; the two addresses that used to hold one half each now redirect
  // there, so a bookmark still lands on the whole.
  "/settings/workspace",
  "/settings/focus",
  // Module-owned redirect aliases. Same contract as the core ones above:
  // the address outlived the screen, and a bookmark should land somewhere.
  // `/warehouse` was the module's document list, now History.
  // `/warehouse/profile` was the warehouse profile tab, now the Configuration
  // screen at `/warehouse/settings`, query string and hash carried over.
  "/warehouse",
  "/warehouse/profile",
  // `/maker/bom` was the second formula editor, removed when composing a
  // formula moved onto the recipe screen; redirects to the catalog.
  "/maker/bom",
  // The old zone drill-down: a card on the storages list and the zone page
  // itself handed this address out, and links written then outlive the
  // screen. It now opens the storages screen with that node selected.
  "/inventory/locations/zone/:zoneId",
];

// ---------------------------------------------------------------------------
// 1. App.tsx route extraction
// ---------------------------------------------------------------------------

/**
 * Resolve `<Route path>` values to absolute patterns. Assumes App.tsx keeps
 * its current layout: relative paths are children of the `/` shell route
 * (or nested `settings` block); `index` and `*` routes are skipped; the
 * dynamic `{shellModules.map(...)}` / `{flatRoutes.map(...)}` /
 * `{settingsSections.map(...)}` blocks contain no static paths.
 */
function extractRoutes() {
  const lines = readFileSync(APP_TSX, "utf8").split(/\r?\n/);
  const routes = new Set();
  const stack = []; // absolute path contexts
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes("</Route>")) {
      stack.pop();
      continue;
    }
    // A tag, not the word: a docstring naming `<Routes>` is prose, and read
    // as a tag it pushes a phantom context every later route is resolved
    // under — which is how `/items` came out of this script as `/login/items`.
    // The lookahead rather than `[\s>]` because prettier ends some opening
    // tags right after the name, and end-of-line is not a space to a regex.
    if (!/<Route(?![A-Za-z0-9_])/.test(lines[i])) continue;

    // Find the path prop within the opening tag span (may span lines),
    // then scan to the tag end to detect self-closing (`/>`). Prettier
    // format puts the closing `>`/`/>` of the ROUTE tag at the same
    // indentation as `<Route` — inner JSX in `element={...}` is indented
    // deeper, so it cannot be mistaken for the tag end.
    let path = null;
    let selfClosing = false;
    const indent = lines[i].match(/^\s*/)[0].length;
    let j = i;
    for (; j < lines.length; j++) {
      const trimmed = lines[j].trimEnd();
      const atTagLevel = lines[j].match(/^\s*/)[0].length === indent;
      if (atTagLevel && trimmed.endsWith("/>")) selfClosing = true;
      const m = path == null ? lines[j].match(/path="([^"]+)"/) : null;
      if (m) path = m[1];
      if (atTagLevel && (trimmed.endsWith("/>") || trimmed.endsWith(">")))
        break;
    }
    if (path == null) continue;

    if (path === "index" || path === "*") continue;
    const resolved = path.startsWith("/")
      ? path
      : joinPath(stack[stack.length - 1] ?? "", path);
    routes.add(resolved);
    if (!selfClosing) stack.push(resolved);
  }
  return routes;
}

function joinPath(parent, child) {
  return `${parent.endsWith("/") ? parent.slice(0, -1) : parent}/${child}`;
}

// ---------------------------------------------------------------------------
// 1b. Module route extraction (src/modules/<name>/module.ts)
// ---------------------------------------------------------------------------

/**
 * Contents of a `key: [ ... ]` / `key: { ... }` literal in a module file.
 *
 * Brace counting rather than a parser: module.ts files are prettier-formatted
 * registration calls, and the alternative (importing them) would need a DOM,
 * i18n and every icon package the modules pull in. Comments are blanked
 * first: an apostrophe in `// the module's own options` would otherwise open
 * a string that swallows the closing brace.
 */
export function sliceBlock(source, key) {
  const text = blankComments(source);
  const start = text.search(new RegExp(`^\\s*${key}:\\s*[[{]`, "m"));
  if (start === -1) return null;
  const braceStart = text.slice(start).search(/[[{]/) + start;
  const open = text[braceStart];
  const close = open === "[" ? "]" : "}";
  let depth = 0;
  for (let i = braceStart; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"' || ch === "'" || ch === "`") {
      // Skip the string body: a path may contain nothing structural, but a
      // template literal can contain `${...}` braces that would unbalance us.
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

/**
 * Routes a module contributes, and the references its own registration
 * implies (nav items, launcher tile target).
 */
function readModules() {
  const routes = []; // { path, module }
  const references = new Set();
  // Modules whose own nav carries the settings screen (an item whose path
  // ends in "/settings") — their settings are reachable through the module,
  // so no link has to name their /settings/modules instance.
  const ownSettingsScreens = new Set();

  for (const [name, file] of moduleFiles()) {
    const text = readFileSync(file, "utf8");

    const navBlock = sliceBlock(text, "moduleNav");
    const basePath = navBlock
      ? (navBlock.match(/\bbasePath:\s*"([^"]*)"/)?.[1] ?? "").replace(
          /\/$/,
          "",
        )
      : null;

    // Nav items are references: ModuleShell renders each as a link.
    if (navBlock) {
      const itemsBlock = sliceBlock(navBlock, "items");
      for (const p of itemsBlock ? pathsIn(itemsBlock) : []) {
        if (p.startsWith("/")) references.add(p);
        else if (p === "") references.add(basePath);
        else references.add(`${basePath}/${p}`);
        if (
          (p.startsWith("/") ? p : `${basePath}/${p}`).endsWith("/settings")
        ) {
          ownSettingsScreens.add(name);
        }
      }
    }

    const routesBlock = sliceBlock(text, "routes");
    const modulePaths = [];
    if (routesBlock) {
      // Index routes render at the module base path — that path is the one
      // that needs a link, and it is checked in its own right.
      for (const entry of routesBlock.split(/\},?\s*(?=\{)/)) {
        if (/\bindex:\s*true/.test(entry)) continue;
        for (const p of pathsIn(entry)) {
          if (!p.startsWith("/")) continue; // relative: mounted under a base
          modulePaths.push(p);
          routes.push({ path: p, module: name });
        }
      }
    }

    // The launcher tile and the module switcher link here — mirror of
    // resolveModuleTarget() in src/lib/moduleRegistry/resolveModuleTarget.ts.
    if (/^\s*launcher:\s*\{/m.test(text)) {
      const launcherBlock = sliceBlock(text, "launcher");
      const linkTo = launcherBlock?.match(/\blinkTo:\s*"([^"]*)"/)?.[1];
      const target = linkTo ?? basePath ?? modulePaths[0];
      if (target) references.add(target);
    }

    // `settingsSections` is deliberately NOT checked. SettingsShell builds a
    // sidebar entry for every section the registry reports, from the same
    // list App.tsx mounts — one loop, so a section cannot be mounted without
    // being linked. `moduleNav` is a second, hand-written list, which is why
    // module `routes` DO need this gate.
  }

  return { routes, references, ownSettingsScreens };
}

// ---------------------------------------------------------------------------
// 2. Reference collection
// ---------------------------------------------------------------------------

const REFERENCE_RES = [
  // JSX: to="/x" / to={"/x"} / to={`/x${...}`} / href="/x"
  // The optional brace matters: `to={`/x/${id}`}` is how every dynamic link
  // in this app is written, and without it the whole shape was invisible.
  /\b(?:to|href)\s*=\s*\{?\s*(?:"([^"]+)"|`([^`]*)`)/g,
  // Data objects: to: "/x" / to: `/x${...}` (SettingsShell sidebar items)
  /\bto\s*:\s*(?:"([^"]+)"|`([^`]*)`)/g,
  // Programmatic: navigate("/x") / navigate(`/x${...}`)
  /\bnavigate\(\s*(?:"([^"]+)"|`([^`]*)`)/g,
  // Launcher action items: linkTo: "/x" — rendered as <Link to={item.linkTo}>
  /\blinkTo\s*[:=]\s*(?:"([^"]+)"|`([^`]*)`)/g,
];

// A `<Navigate to="/x">` is a forwarding address, not a way in. Counting it
// as a reference let /inventory/locations/:id sit unreachable for months: the
// only thing naming it was the redirect from its own retired alias, and a
// person cannot arrive at a page by being redirected away from nowhere.
const NAVIGATE_ELEMENT_RE = /<Navigate\b[^>]*>/g;

/** Every route reference in one file's source. */
export function referencesIn(text) {
  text = text.replace(NAVIGATE_ELEMENT_RE, "");
  const refs = new Set();
  for (const re of REFERENCE_RES) {
    let m;
    while ((m = re.exec(text)) !== null) {
      const raw = m[1] ?? m[2];
      if (!raw || !raw.startsWith("/")) continue;
      refs.add(raw);
    }
  }
  return refs;
}

function collectReferences() {
  const refs = new Set();
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "i18n" || entry.name === "__tests__") continue;
        walk(full);
      } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
        if (/\.(test|spec)\./.test(entry.name)) continue;
        for (const ref of referencesIn(readFileSync(full, "utf8"))) {
          refs.add(ref);
        }
      }
    }
  };
  walk(SRC);
  refs.delete(APP_TSX); // definitions, not references
  return refs;
}

// ---------------------------------------------------------------------------
// 3. Matching
// ---------------------------------------------------------------------------

function normalize(p) {
  return p.replace(/[?#].*$/, "").replace(/\/+$/, "");
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// A route writes its variable segment `:id`, a reference writes it
// `${item.id}`. Both collapse to "one segment" so `/warehouse/documents/:id` and
// `to={`/warehouse/documents/${doc.id}`}` line up.
//
// The route is always the pattern and the reference always the subject —
// never the reverse. Letting a reference act as the pattern makes
// `to={`/warehouse/documents/${doc.id}`}` cover `/warehouse/settings` as well, and a
// gate that accepts any sibling link is not a gate.
const PLACEHOLDER_RE = /:[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]*\}/g;

/** `/a/:id` and `/a/${x}` → /^\/a\/[^/]+$/ */
function toRegex(pattern) {
  let out = "";
  let last = 0;
  for (const m of pattern.matchAll(PLACEHOLDER_RE)) {
    out += escapeRe(pattern.slice(last, m.index)) + "[^/]+";
    last = m.index + m[0].length;
  }
  out += escapeRe(pattern.slice(last));
  return new RegExp(`^${out}$`);
}

/** Placeholders collapsed to a literal segment, so a pattern can match it. */
function literalize(pattern) {
  return pattern.replace(PLACEHOLDER_RE, "x");
}

export function isCovered(route, references) {
  const regex = toRegex(route);
  const normRoute = normalize(route);
  for (const ref of references) {
    const normRef = normalize(ref);
    if (regex.test(literalize(normRef))) return true;
    // Prefix reference: `` to={`/settings/`} `` + a path appended elsewhere.
    if (normRoute.startsWith(normRef) && normRef.endsWith("/")) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Parameterized route instances.
//
// A route with a variable segment is satisfied by ONE link for every
// instance at once: `to="/settings/modules/webhooks"` covered
// `/settings/modules/:name`, and with it the approvals and stats settings
// screens — reachable only by typing the address — looked fine to this
// gate. For a route whose parameter enumerates a known set, each instance
// is its own promise and gets its own reference.
//
// The instance space of `/settings/modules/:name` is declared server-side:
// every backend module manifest with `has_settings_schema: true` exposes
// one of these screens. The backend tree sits next to the frontend one on
// disk, and the frontend container mounts it read-only, for exactly this
// kind of cross-tree fact — same source as moduleGateNames.test.ts.
const SETTINGS_ROUTE = "/settings/modules/:name";
const BACKEND_MANIFESTS = resolve(ROOT, "..", "backend", "app", "modules");

/** Modules whose backend manifests declare a settings schema. */
export function settingsInstances() {
  if (!existsSync(BACKEND_MANIFESTS)) return [];
  const names = [];
  for (const entry of readdirSync(BACKEND_MANIFESTS, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const manifest = join(BACKEND_MANIFESTS, entry.name, "manifest.json");
    if (!existsSync(manifest)) continue;
    let parsed;
    try {
      parsed = JSON.parse(readFileSync(manifest, "utf8"));
    } catch {
      continue;
    }
    if (parsed.has_settings_schema === true) {
      names.push(parsed.name ?? entry.name);
    }
  }
  return names.sort();
}

/**
 * Module-settings instances nothing leads to. A module's settings count as
 * reached when a reference names its instance, or when the module keeps its
 * settings screen inside itself (a moduleNav item whose path ends in
 * "/settings" — recipes, equipment), which a person arrives at through the
 * module. Only the parameterized settings route is instance-checked today;
 * other parameterized routes keep the one-link-covers-all reading.
 */
export function settingsInstanceGaps(
  route,
  references,
  instances,
  ownSettingsScreens,
) {
  if (route !== SETTINGS_ROUTE) return [];
  const prefix = SETTINGS_ROUTE.replace(/:[^/]+$/, "");
  return instances
    .filter((name) => !ownSettingsScreens.has(name))
    .map((name) => `${prefix}${name}`)
    .filter((instance) => !references.has(instance));
}

/**
 * One reported line of an unreachable route. Instance reports carry a
 * parenthesised note, so they are not keys of the owners map — naming no
 * owner beats printing `[undefined]`, which reads like a broken tool rather
 * than a missing link.
 */
export function unreachableLine(entry, owner) {
  return owner ? `  - ${entry}  [${owner}]` : `  - ${entry}`;
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

  const staticRoutes = [...extractRoutes()].sort();
  const {
    routes: moduleRoutes,
    references: moduleReferences,
    ownSettingsScreens,
  } = readModules();

  // One namespace: a module route and a static route are the same kind of
  // promise to the reader, and the same kind of dead end when nothing links
  // to it. `owner` only shapes the error message.
  const owners = new Map(staticRoutes.map((r) => [r, "App.tsx"]));
  for (const { path, module } of moduleRoutes) {
    if (!owners.has(path)) owners.set(path, `module: ${module}`);
  }
  const routes = [...owners.keys()].sort();

  const references = collectReferences();
  for (const ref of moduleReferences) references.add(ref);

  const allowlisted = DEEPLINK_ALLOWLIST.filter((p) => routes.includes(p));
  // The "/" shell route is the app root (AppShell) — reachable by definition.
  const unreachable = routes
    .filter((r) => r !== "/")
    .filter((r) => !allowlisted.includes(r) && !isCovered(r, references));

  // Instance-level check for the parameterized settings route: the module
  // whose settings screen nothing links to is exactly the dead end this
  // gate exists for.
  const settingsRoute = routes.find((r) => r === SETTINGS_ROUTE);
  const instanceGaps = settingsRoute
    ? settingsInstanceGaps(
        settingsRoute,
        references,
        settingsInstances(),
        ownSettingsScreens,
      )
    : [];
  for (const gap of instanceGaps) {
    unreachable.push(
      `${gap} (module settings: no link names this module's instance)`,
    );
  }

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify({ unreachable }, null, 2) + "\n",
    );
    console.log(
      `route baseline written: ${unreachable.length} unreachable route(s) → scripts/route-reachability-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? new Set(JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unreachable)
      : new Set();
  const newUnreachable = unreachable.filter((r) => !baseline.has(r));
  const fixed = [...baseline].filter((r) => !unreachable.includes(r));

  console.log(
    `route-reachability: ${routes.length} route(s) ` +
      `(${staticRoutes.length} static, ${routes.length - staticRoutes.length} from modules), ` +
      `${references.size} reference(s), ${allowlisted.length} allowlisted deeplink(s), ` +
      `${unreachable.length} unreachable`,
  );

  if (newUnreachable.length > 0) {
    console.error(`\n✗ NEW unreachable route(s) (${newUnreachable.length}):`);
    for (const r of newUnreachable)
      console.error(unreachableLine(r, owners.get(r)));
    console.error(
      "\nAdd a nav entry / link referencing the route, remove the dead route," +
        " or — only for genuine external entry points — add it to" +
        " DEEPLINK_ALLOWLIST with a comment.",
    );
    process.exit(1);
  }
  if (fixed.length > 0) {
    console.log(
      `✓ no new unreachable routes (${fixed.length} became reachable since baseline — run --write-baseline to refresh).`,
    );
  } else {
    console.log("✓ no new unreachable routes");
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
