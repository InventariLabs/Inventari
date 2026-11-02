#!/usr/bin/env node
/**
 * Which modules the store has to show — carried across the container boundary
 * as a snapshot.
 *
 * The invariant: every module `GET /modules/available` returns is visible in
 * the App Store under the default filter. Nothing used to hold the store to
 * that. The category tabs once came off the launcher tile, so the six modules
 * that have no tile fell out of all five of them; that particular cause is
 * gone, but the shape of it is not — any predicate the store grows next (a
 * filter, a search haystack, a label lookup) can drop a module silently, and a
 * module nobody can see is a module nobody can switch on.
 *
 * The list is backend truth: every module directory with a manifest, minus the
 * ones declaring `is_reference` (a worked example is documentation, not a
 * product — app/api/modules.py skips them), plus the virtual entries that file
 * adds by hand. Neither container can see the other's tree — the frontend
 * mounts ./frontend, the backend mounts ./backend — so the snapshot is what
 * crosses. Where both trees ARE visible (the host, a pre-commit hook, CI) it is
 * verified against the backend and cannot drift unnoticed.
 *
 *   node check-module-catalog.mjs                 verify (or read-only)
 *   node check-module-catalog.mjs --sync-backend  refresh the snapshot
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SNAPSHOT_PATH = resolve(ROOT, "scripts/module-catalog.json");
const BACKEND_MODULES = resolve(ROOT, "../backend/app/modules");
const MODULES_API = resolve(ROOT, "../backend/app/api/modules.py");

/**
 * Modules with no directory of their own, assembled in the endpoint itself.
 * Parsed rather than listed here so that adding one to the API adds it to the
 * gate; an unreadable block is an error, never an empty answer, because a
 * silently shorter catalog is a gate that stops asking.
 */
function readVirtualModules() {
  const source = readFileSync(MODULES_API, "utf8");
  const start = source.indexOf("virtual_modules = [");
  if (start === -1)
    throw new Error(
      `no 'virtual_modules = [' in ${relative(ROOT, MODULES_API)} — the ` +
        "endpoint changed shape and this gate can no longer read it",
    );

  const end = source.indexOf("\n    ]", start);
  if (end === -1)
    throw new Error(
      `'virtual_modules' in ${relative(ROOT, MODULES_API)} does not close ` +
        "where this gate expects it to",
    );

  return [...source.slice(start, end).matchAll(/name='([a-z_]+)'/g)].map(
    (m) => m[1],
  );
}

/** Every module the store must show, or null when the backend is not mounted. */
function readCatalog() {
  if (!existsSync(BACKEND_MODULES) || !existsSync(MODULES_API)) return null;

  const names = readVirtualModules();
  for (const entry of readdirSync(BACKEND_MODULES, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;

    const manifest = join(BACKEND_MODULES, entry.name, "manifest.json");
    if (!existsSync(manifest)) continue;

    if (JSON.parse(readFileSync(manifest, "utf8")).is_reference !== true)
      names.push(entry.name);
  }
  return names.sort();
}

const snapshot = existsSync(SNAPSHOT_PATH)
  ? JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8"))
  : [];
const actual = readCatalog();

if (process.argv.includes("--sync-backend")) {
  if (actual === null) {
    console.error(
      `✗ --sync-backend needs the backend tree at ${relative(ROOT, BACKEND_MODULES)}`,
    );
    process.exit(1);
  }
  writeFileSync(SNAPSHOT_PATH, `${JSON.stringify(actual, null, 2)}\n`);
  console.log(`✓ module catalog snapshot refreshed (${actual.length} modules)`);
  process.exit(0);
}

if (actual === null) {
  console.log(
    `module-catalog: ${snapshot.length} module(s), snapshot only ` +
      "(backend tree not mounted here)",
  );
  process.exit(0);
}

const added = actual.filter((name) => !snapshot.includes(name));
const removed = snapshot.filter((name) => !actual.includes(name));

if (added.length > 0 || removed.length > 0) {
  for (const name of added) console.error(`MODULE-CATALOG ADDED   ${name}`);
  for (const name of removed) console.error(`MODULE-CATALOG REMOVED ${name}`);
  console.error(
    "✗ module catalog snapshot is stale — run: npm run check:modules:catalog:sync-backend",
  );
  process.exit(1);
}

console.log(
  `module-catalog: ${actual.length} module(s) the store must show, snapshot matches`,
);
