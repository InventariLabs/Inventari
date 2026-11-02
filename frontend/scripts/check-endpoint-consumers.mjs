#!/usr/bin/env node
/**
 * check-endpoint-consumers.mjs
 *
 * Detects backend routes no production frontend code calls.
 *
 * A route without a caller is not automatically a mistake: it may be an
 * integration surface, a webhook, a target for the print agent, or an
 * operational endpoint. So the gate does not forbid it — it forces the
 * absence of UI to be a signed decision, recorded in integration-only.json
 * with a reason and an owner, instead of something nobody ever noticed.
 *
 * Matching is by segment, and the one rule worth stating is why a `${...}`
 * hole is not a wildcard. It matches a `{param}` segment freely. It matches a
 * LITERAL segment only when a literal segment still follows it in the call —
 * otherwise `/stock-takes/${id}` would swallow
 * `/stock-takes/cycle-count-schedules` and report a whole unbuilt feature as
 * consumed. That rule is the outcome of two earlier attempts that did exactly
 * that.
 *
 * Modes:
 *   node check-endpoint-consumers.mjs        # full report, exit 1
 *   node check-endpoint-consumers.mjs --list # print unclaimed routes only
 *
 * There is no baseline: integration-only.json IS the record, and it carries an
 * owner and an expiry per entry so a deferral cannot go quiet.
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { resolve, relative, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const ROUTES_FILE = resolve(SRC, "types/api-routes.ts");
const REGISTER_FILE = resolve(ROOT, "scripts/integration-only.json");

// The frontend's HTTP clients name paths relative to this prefix.
const API_PREFIX = "/api/v1";

// Routes outside the versioned API: health probes, the OpenAPI document, the
// SPA fallback. They have no frontend caller by definition.
const isVersionedApi = (route) => route.startsWith(`${API_PREFIX}/`);

// `getEveryPage` (lib/api/client.ts) is a GET that follows a paged list to its
// end; a reader written with it calls the route as surely as `api.get` does.
const CLIENT_CALL_RE =
  /\b(?:(?:api|http|axios)\s*\.\s*(?:get|post|put|patch|delete|request)|getEveryPage)\s*/g;

const isSpec = (rel) =>
  /\.test\.tsx?$/.test(rel) ||
  rel.startsWith("test/") ||
  rel.includes("__mocks__/");

// The generated files list every route by construction; counting them as
// callers would make the gate report nothing, forever.
const isGenerated = (rel) =>
  rel === "types/api-routes.ts" || rel === "types/api-generated.ts";

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function routesIn(text) {
  return [...text.matchAll(/"(\/[^"]*)"/g)].map((m) => m[1]);
}

/**
 * Every path literal handed to an HTTP client, query string stripped.
 *
 * Scanned rather than matched in one regex, because the type argument between
 * the method and the argument list is not regular: it spans lines and may
 * contain parentheses of its own (`api.get<import("...").Thing>(...)`). A
 * pattern that stopped at the first `(` read that call as no call at all,
 * which is the failure mode this whole gate exists to avoid.
 */
export function callsIn(text) {
  const paths = [];
  for (const match of text.matchAll(CLIENT_CALL_RE)) {
    let i = match.index + match[0].length;
    if (text[i] === "<") {
      let depth = 0;
      for (; i < text.length; i++) {
        if (text[i] === "<") depth++;
        else if (text[i] === ">" && --depth === 0) {
          i++;
          break;
        }
      }
    }
    while (i < text.length && /\s/.test(text[i])) i++;
    if (text[i] !== "(") continue;
    i++;
    while (i < text.length && /\s/.test(text[i])) i++;
    const quote = text[i];
    if (quote !== '"' && quote !== "'" && quote !== "`") continue;
    const end = text.indexOf(quote, i + 1);
    if (end === -1) continue;
    const literal = text
      .slice(i + 1, end)
      .split("?")[0]
      .replace(/\/+$/, "");
    if (literal.startsWith("/")) paths.push(literal);
  }
  return paths;
}

const segments = (path) => path.split("/").filter(Boolean);
const isHole = (segment) => /\$\{/.test(segment);
const isParam = (segment) => segment.startsWith("{") && segment.endsWith("}");

/**
 * Whether one call literal addresses one route.
 *
 * See the header for why a trailing hole may not stand in for a literal.
 */
export function callMatches(call, route) {
  const callSegments = segments(call);
  const routeSegments = segments(route);
  if (callSegments.length !== routeSegments.length) return false;
  return callSegments.every((callSegment, i) => {
    const routeSegment = routeSegments[i];
    if (!isHole(callSegment)) return callSegment === routeSegment;
    if (isParam(routeSegment)) return true;
    return callSegments.slice(i + 1).some((s) => !isHole(s));
  });
}

export function unclaimedRoutes(routes, calls) {
  return routes
    .filter(isVersionedApi)
    .filter(
      (route) =>
        !calls.some((call) =>
          callMatches(call, route.slice(API_PREFIX.length)),
        ),
    )
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/**
 * Read the register of routes that intentionally have no UI.
 *
 * Every entry needs a reason, an owner and an expiry, for the reason the
 * backend's permission deferrals do: a suppression with nobody's name on it
 * outlives the question it was standing in for.
 */
export function readRegister(raw, today) {
  const errors = [];
  const claimed = new Set();
  for (const [route, entry] of Object.entries(raw.routes ?? {})) {
    const where = `integration-only.json → "${route}"`;
    if (!entry?.reason) errors.push(`${where}: no reason given.`);
    if (!entry?.owner)
      errors.push(
        `${where}: names nobody. An unowned entry is how a gap goes quiet.`,
      );
    const expires = entry?.expires ? new Date(entry.expires) : null;
    if (!expires || Number.isNaN(expires.valueOf()))
      errors.push(`${where}: expires must be a YYYY-MM-DD date.`);
    else if (expires < today)
      errors.push(
        `${where}: expired on ${entry.expires} — ${entry.owner ?? "nobody"} was to decide: build the UI, or delete the route.`,
      );
    if (entry?.reason && entry?.owner && expires && expires >= today)
      claimed.add(route);
  }
  return { claimed, errors };
}

function main() {
  const routes = routesIn(readFileSync(ROUTES_FILE, "utf8"));
  const calls = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter((rel) => /\.tsx?$/.test(rel) && !isSpec(rel) && !isGenerated(rel))
    .flatMap((rel) => callsIn(readFileSync(resolve(SRC, rel), "utf8")));

  const unclaimed = unclaimedRoutes(routes, calls);
  const raw = existsSync(REGISTER_FILE)
    ? JSON.parse(readFileSync(REGISTER_FILE, "utf8"))
    : { routes: {} };
  const { claimed, errors } = readRegister(raw, new Date());

  if (process.argv.includes("--list")) {
    for (const route of unclaimed) console.log(route);
    process.exit(0);
  }

  const stale = [...claimed].filter((r) => !unclaimed.includes(r));
  const missing = unclaimed.filter((r) => !claimed.has(r));

  if (missing.length > 0) {
    console.error(
      `Backend route(s) with no frontend caller and no entry in integration-only.json (${missing.length}):`,
    );
    for (const route of missing) console.error(`  - ${route}`);
    console.error(
      "\nEither wire the route into the UI, or record the decision in " +
        "frontend/scripts/integration-only.json with a reason, an owner and an expiry.",
    );
  }
  for (const error of errors) console.error(`  - ${error}`);
  if (stale.length > 0) {
    console.log(
      `\n${stale.length} entr(y/ies) in integration-only.json now have a caller and can be removed:`,
    );
    for (const route of stale) console.log(`  - ${route}`);
  }

  if (missing.length > 0 || errors.length > 0) process.exit(1);
  console.log(
    `Every one of the ${routes.filter(isVersionedApi).length} API routes is either called from the UI or recorded as integration-only.`,
  );
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
