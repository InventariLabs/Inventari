#!/usr/bin/env node
/**
 * The edge's 404 rules must not answer an application route or a built file.
 *
 * nginx answers a request with the first regex location that matches, before
 * the single-page fallback. The rules that turn scanner probes away (a path
 * naming another stack, or a backup copy of a file) are patterns over every
 * address the instance serves, so a route named `/vendor/...` or a built file
 * named `report.old` would stop being reachable while nothing else failed.
 *
 * This gate reads the rules from `frontend/nginx.conf` — every regex location
 * that answers `return 404;`, in file order, because the first match wins — and
 * matches them against the route table `check-route-reachability.mjs` reads
 * (App.tsx, each module's `routes` and the redirect table) and against every
 * file of the built `dist/`. It runs after the build in `make check-frontend`;
 * a checkout with no build has nothing to measure and is refused rather than
 * skipped.
 *
 * A route's name is not the only address it serves. `/s/<code>` carries a
 * label's or a document number's own text, and a code can end in `.old` or
 * hold a `~`; a pattern check alone would call that address clear while the
 * scanner rule answers the printed label with 404. `TEXT_VALUES` gives every
 * such route an example value, and the gate refuses a route that carries a
 * person's text with none.
 *
 * Usage: node scripts/check-edge-probes.mjs [--dist <dir>]
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

import { routePaths } from "./check-route-reachability.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const NGINX = resolve(ROOT, "nginx.conf");
const DIST = resolve(ROOT, "dist");

const LOCATION_HEAD = /^\s*location\s+(~[*]?)\s+(\S+)\s*\{/;
const RETURN_404 = /^\s*return\s+404;\s*$/;

/**
 * An example value for every route whose variable part is a person's text.
 *
 * A `:code` segment is a label's or a document number's code, and a `*` splat
 * carries the whole rest of the address; the application takes what the
 * operator typed, so such a code can end in `.old`, hold a `~` or read like
 * `VALVE.CGI2`. The edge rules are patterns over the whole address, so an
 * example value is the only way to prove they leave the address the app prints
 * alone. Every route that carries text needs a row here; `main` refuses one
 * with none.
 */
export const TEXT_VALUES = [
  // The address a printed QR opens (backend core/scan_links.py; the `s/*`
  // redirect in src/lib/legacyRedirects.tsx answers it).
  { route: "/s/*", value: "RACK-7.OLD" },
  // The address the first stickers opened (printing/module.ts).
  { route: "/labels/scan/:code", value: "PALLET~" },
];

/** Whether a route's variable part holds a person's text, not an id. */
export function carriesText(route) {
  return route
    .split("/")
    .some((segment) => /^(?:\*|:\w*[Cc]ode)$/.test(segment));
}

/** The address a `TEXT_VALUES` row serves, its variable part set to the value. */
export function exampleAddress({ route, value }) {
  return route
    .split("/")
    .map((segment) =>
      /^(?:\*|:[A-Za-z_][A-Za-z0-9_]*)$/.test(segment) ? value : segment,
    )
    .join("/");
}

/**
 * Every regex location of the config, in file order, with whether its whole
 * body is `return 404;`.
 *
 * Brace counting over lines rather than one expression: the file is
 * hand-formatted one directive per line, and a nested block inside a location
 * must not end the scan early. A one-line body is read from its own line.
 */
export function regexLocations(nginxText) {
  const lines = nginxText.split("\n").map((line) => line.split("#", 1)[0]);
  const locations = [];
  let index = 0;
  while (index < lines.length) {
    const head = LOCATION_HEAD.exec(lines[index]);
    if (!head) {
      index += 1;
      continue;
    }
    let depth = (lines[index].match(/{/g) ?? []).length;
    depth -= (lines[index].match(/}/g) ?? []).length;
    const body = depth <= 0 ? [inlineBody(lines[index])] : [];
    while (index < lines.length - 1 && depth > 0) {
      index += 1;
      depth += (lines[index].match(/{/g) ?? []).length;
      depth -= (lines[index].match(/}/g) ?? []).length;
      body.push(depth > 0 ? lines[index] : inlineBody(lines[index]));
    }
    locations.push({
      pattern: head[2],
      ignoreCase: head[1] === "~*",
      notFound: isNotFound(body),
    });
    index += 1;
  }
  return locations;
}

/** The text between the braces of a one-line block, without the closing brace. */
function inlineBody(line) {
  const open = line.indexOf("{");
  return open === -1 ? "" : line.slice(open + 1).split("}", 1)[0];
}

/** Whether the only statement of a location body is `return 404;`. */
function isNotFound(body) {
  const statements = body.map((line) => line.trim()).filter(Boolean);
  return statements.length === 1 && RETURN_404.test(statements[0]);
}

/**
 * The paths whose first matching regex location answers 404, with the rule
 * that takes them.
 *
 * nginx evaluates the regex locations in file order and answers with the first
 * match. A path an earlier, ordinary location matches is served by that one and
 * is reported by neither list. A pattern that does not compile in JavaScript is
 * reported on its own: a gate that cannot measure a rule must not pass it.
 */
export function blockedPaths(locations, paths) {
  const blocked = [];
  const broken = new Set();
  const compiled = locations.map((location) => {
    try {
      return new RegExp(location.pattern, location.ignoreCase ? "i" : "");
    } catch {
      broken.add(location.pattern);
      return null;
    }
  });
  for (const path of paths) {
    const match = compiled.findIndex((regex) => regex?.test(path) === true);
    if (match !== -1) {
      const location = locations[match];
      if (location.notFound) blocked.push({ path, pattern: location.pattern });
    }
  }
  return { blocked, broken: [...broken] };
}

/** Every file of `dir` as the URI the Web server serves it at. */
export function builtFiles(dir, base = dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...builtFiles(full, base));
    else if (entry.isFile()) {
      files.push(`/${relative(base, full).split(sep).join("/")}`);
    }
  }
  return files;
}

function main() {
  const distAt = process.argv.indexOf("--dist");
  const dist = distAt === -1 ? DIST : resolve(process.argv[distAt + 1]);
  const locations = regexLocations(readFileSync(NGINX, "utf8"));
  const refusals = locations.filter((location) => location.notFound);
  if (refusals.length === 0) {
    console.error(
      "edge-probes: nginx.conf has no regex location that answers 404; the " +
        "scanner-probe rules the edge promises are missing",
    );
    return 1;
  }
  if (!existsSync(join(dist, "index.html"))) {
    console.error(
      `edge-probes: ${dist}/index.html not found — build first ` +
        "(`npm run build`, or `make check-frontend` which builds before it gates).",
    );
    return 1;
  }

  const routes = routePaths();
  const files = builtFiles(dist);
  const examples = TEXT_VALUES.map((entry) => ({
    ...entry,
    address: exampleAddress(entry),
  }));
  const missing = routes.filter(
    (route) =>
      carriesText(route) &&
      !TEXT_VALUES.some((entry) => entry.route === route),
  );
  const stale = TEXT_VALUES.filter((entry) => !routes.includes(entry.route));
  const routeByAddress = new Map(
    examples.map((entry) => [entry.address, entry.route]),
  );
  const { blocked, broken } = blockedPaths(locations, [
    ...routes,
    ...files,
    ...routeByAddress.keys(),
  ]);

  console.log(
    `edge-probes: ${refusals.length} 404 rule(s), ${routes.length} route(s), ` +
      `${files.length} built file(s), ${examples.length} data value(s)`,
  );
  if (broken.length > 0) {
    console.error(
      `\n✗ regex location(s) this gate cannot read as a JavaScript pattern: ${broken.join(", ")}`,
    );
  }
  if (missing.length > 0) {
    console.error(
      `\n✗ route(s) whose segment is a person's text and that have no example ` +
        `value (${missing.length}):`,
    );
    for (const route of missing) console.error(`  - ${route}`);
    console.error(
      "\nAdd a row to TEXT_VALUES in scripts/check-edge-probes.mjs: an address " +
        "the application prints is not measured until its value is known.",
    );
  }
  if (stale.length > 0) {
    console.error(
      `\n✗ example value(s) for a route the application no longer serves (${stale.length}):`,
    );
    for (const { route } of stale) console.error(`  - ${route}`);
    console.error("\nRemove the row from TEXT_VALUES, or restore the route.");
  }
  if (blocked.length > 0) {
    console.error(
      `\n✗ ${blocked.length} address(es) the application serves are answered 404 by the edge:`,
    );
    for (const { path, pattern } of blocked) {
      const route = routeByAddress.get(path);
      console.error(
        route
          ? `  ${path}  (${route})  ←  ${pattern}`
          : `  ${path}  ←  ${pattern}`,
      );
    }
    console.error(
      "\nRename the route or the file, or narrow the rule in frontend/nginx.conf so " +
        "it no longer covers an address the application serves.",
    );
  }
  const failed =
    missing.length > 0 ||
    stale.length > 0 ||
    blocked.length > 0 ||
    broken.length > 0;
  return failed ? 1 : 0;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === resolve(import.meta.filename)
) {
  process.exitCode = main();
}
