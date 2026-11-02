#!/usr/bin/env node
/**
 * check-e2e-wait-for-timeout.mjs
 *
 * `page.waitForTimeout(n)` in an E2E spec is a guess about how long the app
 * takes. Too short and the test flakes; long enough and it hides the state the
 * test never checked — the documents spec "confirmed" a document by clicking,
 * sleeping two seconds and accepting either outcome. Nothing in lint counts
 * them, so the number only ever went up.
 *
 * A ratchet, not a ban: the calls that exist are recorded in
 * `e2e-wait-for-timeout-baseline.json` and the count may fall, never rise.
 * Replace a wait with an `expect(...)` / `expect.poll(...)` on the state it was
 * waiting for, then lower the baseline with `--write-baseline`.
 *
 * Modes:
 *   node check-e2e-wait-for-timeout.mjs                  # exit 1 above the baseline
 *   node check-e2e-wait-for-timeout.mjs --write-baseline # record the current count
 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const E2E = resolve(ROOT, "tests/e2e");
const BASELINE = resolve(ROOT, "scripts/e2e-wait-for-timeout-baseline.json");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/** Number of `waitForTimeout(` calls in one file's text. */
export function countWaits(text) {
  return (text.match(/\.waitForTimeout\s*\(/g) ?? []).length;
}

function main() {
  let total = 0;
  for (const file of walk(E2E)) {
    if (/\.tsx?$/.test(file)) total += countWaits(readFileSync(file, "utf8"));
  }

  if (process.argv.includes("--write-baseline")) {
    writeFileSync(BASELINE, JSON.stringify({ count: total }, null, 2) + "\n");
    console.log(`waitForTimeout baseline written: ${total}`);
    return;
  }

  const { count: allowed } = JSON.parse(readFileSync(BASELINE, "utf8"));
  if (total > allowed) {
    console.error(
      `waitForTimeout in tests/e2e: ${total}, baseline ${allowed}. Wait on the state with expect()/expect.poll() instead of a sleep.`,
    );
    process.exit(1);
  }
  if (total < allowed) {
    console.log(
      `waitForTimeout in tests/e2e fell to ${total} (baseline ${allowed}) — run with --write-baseline to lock it in.`,
    );
  }
}

if (process.argv[1] && resolve(process.argv[1]) === new URL(import.meta.url).pathname) {
  main();
}
