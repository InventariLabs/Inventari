#!/usr/bin/env node
/**
 * check-title-case.mjs
 *
 * Buttons, captions, headings and labels are sentence case (`UI_GUIDELINES.md`,
 * "Badges and chips"): "Create return", not "Create Return". The warehouse
 * and purchase-order catalogs were written with every word capitalised, and
 * this gate stops the habit coming back.
 *
 * A string is Title Case when it has two to five words, none of its text is
 * prose punctuation, and at least two of its words are ordinary words written
 * with a capital: the first always is, so one more is what gives it away
 * ("Create Return", "Send to Vendor"). An acronym ("Export CSV") is a word
 * that is written in capitals whatever the sentence, not a second capital. Names of modules are proper names and sit in the
 * baseline, keyed by file and key path with the text they held: change the
 * string and it is a new string again.
 *
 * Only the English catalogs of the two modules named below are read; the other
 * four languages have their own capitalisation rules.
 *
 * Modes:
 *   node check-title-case.mjs                    # report and exit 1
 *   node check-title-case.mjs --baseline         # only NEW or CHANGED strings fail
 *   node check-title-case.mjs --write-baseline   # snapshot current
 *   node check-title-case.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/title-case-baseline.json
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { diffBaseline, strings } from "./check-vocabulary.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE_PATH = join(ROOT, "scripts/title-case-baseline.json");
const CATALOGS = [
  "src/modules/warehouse/i18n/en.json",
  "src/modules/purchase_orders/i18n/en.json",
];

const MIN_WORDS = 2;
const MAX_WORDS = 5;

/** Whether a catalog value is written with a capital on every noun. */
export function isTitleCase(value) {
  // A placeholder is a word the sentence has not written yet.
  const text = value.replace(/\{\{[^}]*\}\}/g, " ").trim();
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length < MIN_WORDS || words.length > MAX_WORDS) return false;
  if (/[.?!:;—]/.test(text)) return false;
  const capitalised = words.filter((word) => /^[A-Z][a-z]/.test(word));
  return capitalised.length >= 2;
}

/** Findings of one parsed catalog, keyed `file::path`. */
export function findingsOf(file, catalog) {
  const found = {};
  for (const { path, value } of strings(catalog)) {
    if (isTitleCase(value)) found[`${file}::${path}`] = value;
  }
  return found;
}

export function collectFindings(files = CATALOGS) {
  const found = {};
  for (const file of files) {
    const rel = relative(ROOT, join(ROOT, file));
    Object.assign(
      found,
      findingsOf(rel, JSON.parse(readFileSync(join(ROOT, file), "utf8"))),
    );
  }
  return found;
}

function runCli() {
  const args = process.argv.slice(2);
  const quiet = args.includes("--quiet");
  const findings = collectFindings();

  if (args.includes("--write-baseline")) {
    const sorted = Object.fromEntries(Object.entries(findings).sort());
    writeFileSync(BASELINE_PATH, JSON.stringify(sorted, null, 2) + "\n");
    console.log(
      `title-case baseline written: ${Object.keys(sorted).length} string(s) → scripts/title-case-baseline.json`,
    );
    return;
  }

  const baseline = args.includes("--baseline")
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
    : {};
  const { added, changed } = diffBaseline(findings, baseline);
  const failing = [...added, ...changed];

  if (failing.length > 0) {
    if (!quiet) {
      console.error(
        `check-title-case: ${failing.length} English string(s) are Title Case; buttons, captions and headings are sentence case (UI_GUIDELINES.md):`,
      );
      for (const key of failing) {
        const [file, path] = key.split("::");
        console.error(`  ${file} ${path}\n    "${findings[key]}"`);
      }
    }
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `check-title-case: OK — ${Object.keys(findings).length} Title Case string(s), all in the baseline.`,
    );
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
