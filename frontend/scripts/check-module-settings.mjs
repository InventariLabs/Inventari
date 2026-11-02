#!/usr/bin/env node
/**
 * Which modules declare module-level settings — carried across the container
 * boundary as a snapshot.
 *
 * The invariant being served lives in UI_GUIDELINES §2.14a: a module that has
 * settings must offer a way into them from its own nav bar, or the only
 * entrance is /settings/modules/<name>, which is reached from the App Store
 * and leads back out to it — the user leaves the module to change how the
 * module behaves. `moduleSettingsReachability.test.ts` checks that, and to
 * check it, it needs the list.
 *
 * The list is backend truth: `has_settings_schema` in each module's
 * manifest.json, pinned to `BaseModule.get_settings_schema` by
 * backend/tests/unit/test_manifest_settings_schema.py. Neither container can
 * see the other's tree — the frontend mounts ./frontend, the backend mounts
 * ./backend — so the snapshot is what crosses. Where both trees ARE visible
 * (the host, a pre-commit hook, CI) it is verified against the manifests and
 * cannot drift unnoticed.
 *
 *   node check-module-settings.mjs                 verify (or read-only)
 *   node check-module-settings.mjs --sync-backend  refresh the snapshot
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SNAPSHOT_PATH = resolve(ROOT, "scripts/module-settings.json");
const BACKEND_MODULES = resolve(ROOT, "../backend/app/modules");

/** Module names declaring settings, or null when the backend is not mounted. */
function readManifests() {
  if (!existsSync(BACKEND_MODULES)) return null;

  const declared = [];
  for (const entry of readdirSync(BACKEND_MODULES, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;

    const manifest = join(BACKEND_MODULES, entry.name, "manifest.json");
    if (!existsSync(manifest)) continue;

    if (JSON.parse(readFileSync(manifest, "utf8")).has_settings_schema === true)
      declared.push(entry.name);
  }
  return declared.sort();
}

const snapshot = existsSync(SNAPSHOT_PATH)
  ? JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8"))
  : [];
const actual = readManifests();

if (process.argv.includes("--sync-backend")) {
  if (actual === null) {
    console.error(
      `✗ --sync-backend needs the backend tree at ${relative(ROOT, BACKEND_MODULES)}`,
    );
    process.exit(1);
  }
  writeFileSync(SNAPSHOT_PATH, `${JSON.stringify(actual, null, 2)}\n`);
  console.log(
    `✓ module settings snapshot refreshed (${actual.length} modules)`,
  );
  process.exit(0);
}

if (actual === null) {
  console.log(
    `module-settings: ${snapshot.length} module(s), snapshot only ` +
      "(backend tree not mounted here)",
  );
  process.exit(0);
}

const added = actual.filter((name) => !snapshot.includes(name));
const removed = snapshot.filter((name) => !actual.includes(name));

if (added.length > 0 || removed.length > 0) {
  for (const name of added) console.error(`MODULE-SETTINGS ADDED   ${name}`);
  for (const name of removed) console.error(`MODULE-SETTINGS REMOVED ${name}`);
  console.error(
    "✗ module settings snapshot is stale — run: npm run check:modules:sync-backend",
  );
  process.exit(1);
}

console.log(
  `module-settings: ${actual.length} module(s) declare settings, snapshot matches`,
);
