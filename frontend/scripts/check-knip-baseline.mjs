#!/usr/bin/env node
/**
 * check-knip-baseline.mjs
 *
 * Knip dead-code gate with a baseline: fails only on NEW findings.
 * Same pattern as backend/scripts/check_vulture_baseline.py and
 * frontend/scripts/check-i18n-keys.mjs --baseline.
 *
 *   node check-knip-baseline.mjs            # fail only on new findings
 *   node check-knip-baseline.mjs --write-baseline  # snapshot current state
 *   node check-knip-baseline.mjs --full     # full report, exit 0
 *
 * Baseline file: frontend/scripts/knip-baseline.json
 * The goal is an EMPTY baseline — remove dead code, don't grandfather it.
 * Known false positives are handled in frontend/knip.json (entry points,
 * ignore, ignoreDependencies) — add config there, not to the baseline.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const BASELINE_PATH = resolve(ROOT, "scripts/knip-baseline.json");

function runKnip() {
  const result = spawnSync(
    process.execPath,
    [resolve(ROOT, "node_modules/knip/bin/knip.js"), "--reporter", "json"],
    { cwd: ROOT, encoding: "utf8" },
  );
  let data;
  try {
    data = JSON.parse(result.stdout);
  } catch {
    console.error(
      result.stdout || result.stderr || "knip produced no JSON output",
    );
    console.error(`knip exited with status ${result.status}`);
    process.exit(result.status ?? 1);
  }
  return data;
}

/**
 * Flatten knip's JSON report into "category:path[:symbol]" keys.
 * v5.88 reporter shape: { files: string[], issues: [{file, dependencies,
 * devDependencies, unlisted, binaries, unresolved, exports, types}] }.
 * "duplicates" is disabled in knip.json.
 */
function flatten(data) {
  const keys = new Set();
  for (const file of data?.files ?? []) keys.add(`files:${file}`);
  for (const issue of data?.issues ?? []) {
    const file = issue.file ?? "";
    for (const dep of issue.dependencies ?? [])
      keys.add(`dependencies:${dep.name}`);
    for (const dep of issue.devDependencies ?? [])
      keys.add(`devDependencies:${dep.name}`);
    for (const dep of issue.unlisted ?? []) keys.add(`unlisted:${dep.name}`);
    for (const e of issue.exports ?? []) keys.add(`exports:${file}:${e.name}`);
    for (const e of issue.types ?? []) keys.add(`types:${file}:${e.name}`);
  }
  return keys;
}

const args = process.argv.slice(2);
const writeBaseline = args.includes("--write-baseline");
const full = args.includes("--full");

const data = runKnip();
const current = [...flatten(data)].sort();

if (writeBaseline) {
  writeFileSync(
    BASELINE_PATH,
    JSON.stringify({ issues: current }, null, 2) + "\n",
  );
  console.log(
    `knip baseline written: ${current.length} finding(s) → scripts/knip-baseline.json`,
  );
  process.exit(0);
}

if (full) {
  console.log(
    `knip: ${current.length} finding(s) (full report, non-blocking):`,
  );
  for (const key of current) console.log(`  - ${key}`);
  process.exit(0);
}

const baseline = existsSync(BASELINE_PATH)
  ? new Set(JSON.parse(readFileSync(BASELINE_PATH, "utf8")).issues)
  : new Set();
const newFindings = current.filter((k) => !baseline.has(k));
const fixed = [...baseline].filter((k) => !current.includes(k));

if (newFindings.length > 0) {
  console.error(
    `knip baseline regression — NEW finding(s) (${newFindings.length}):`,
  );
  for (const key of newFindings) console.error(`  - ${key}`);
  console.error(
    "\nRemove the dead code. For false positives, adjust frontend/knip.json — do NOT grandfather findings into the baseline.",
  );
  process.exit(1);
}

if (fixed.length > 0) {
  console.log(
    `knip passed baseline: ${current.length} finding(s), ${fixed.length} fixed/removed since baseline. ` +
      "Run --write-baseline to refresh scripts/knip-baseline.json.",
  );
} else {
  console.log(`knip passed baseline: ${current.length} known finding(s).`);
}
process.exit(0);
