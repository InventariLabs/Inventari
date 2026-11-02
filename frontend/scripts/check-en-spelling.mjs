#!/usr/bin/env node
/**
 * check-en-spelling.mjs
 *
 * One spelling per word in the English catalogs.
 *
 * The product vocabulary is "organization" — backend fields, API routes,
 * docs. The English catalogs also carried the British "organisation" (both
 * variants inside a single view), so search-by-word missed half the matches
 * and the copy read as written by two people.
 *
 * The gate scans only the English catalogs. French ("organisation") and
 * German ("Organisation") spell the word that way natively; a gate over all
 * languages would force a misspelling of French to satisfy English.
 *
 * Scans every locale JSON under `src/i18n/locales/en/` and every module
 * catalog named `i18n/en.json`, and fails on "organisation" in any
 * casing, naming file and line.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");

export function lineOffends(line) {
  return /organisation/i.test(line);
}

/** Scans the given files and returns one `path:line` string per offender. */
export function collectOffenders(paths) {
  const offenders = [];
  for (const path of paths) {
    const lines = readFileSync(path, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (lineOffends(line)) {
        offenders.push(`${path}:${i + 1}: ${line.trim().slice(0, 120)}`);
      }
    });
  }
  return offenders;
}

function walk(dir, fileName, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, fileName, out);
    else if (
      entry.endsWith(".json") &&
      (fileName === null || entry === fileName)
    )
      out.push(full);
  }
  return out;
}

function runCli() {
  // Every JSON under the English locale tree; a module carries exactly one
  // English catalog, named en.json under i18n/.
  const files = [
    ...walk(join(ROOT, "i18n", "locales", "en"), null),
    ...walk(join(ROOT, "modules"), "en.json"),
  ];
  const offenders = collectOffenders(files);

  if (offenders.length > 0) {
    console.error(
      `check-en-spelling: ${offenders.length} line(s) use "organisation" — the English catalogs spell it "organization" (French and German catalogs are not scanned):\n` +
        offenders.map((o) => `  ${o}`).join("\n"),
    );
    process.exit(1);
  }

  console.log("check-en-spelling: OK — one spelling in the English catalogs");
}

// The scan and the exit belong to the CLI run only. Under vitest
// `import.meta.url` carries a `/@fs/` prefix, so this comparison is false on
// import — the test suite must be able to load the rule without running the
// gate.
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
