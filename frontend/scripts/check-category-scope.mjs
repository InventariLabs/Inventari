#!/usr/bin/env node
/**
 * check-category-scope.mjs
 *
 * A screen that asks for categories says what it means by them.
 *
 * `useCategories()` with no argument answers "every category this
 * organization has" — module-owned ones included. That is the right answer
 * for naming a row that already stands somewhere, and the wrong one for a
 * picker: the putaway rule editor and the stock-take surplus form both
 * offered "Laptop" while the same policy kept the equipment categories off
 * their lists, so a rule could be written on a category no incoming item
 * would ever match, and a counted item filed under a category the products
 * list then never shows.
 *
 * The hook has every answer a caller needs — `useAllCategories()` when the
 * list names rows that already stand somewhere, `useScopedCategories()` when
 * a general screen offers a picker or a filter (and, with `keepId`, keeps a
 * value a record deliberately carries), or the explicit
 * `excludeModuleContexts` argument for a management screen with its own
 * scope. So this gate does not decide the scope; it demands that the call
 * state one. A bare `useCategories()` is the finding, whatever the file.
 *
 * The scanner is deliberately literal — a call with an empty argument list —
 * because the cost of guessing is a reader learning to skip the output. A
 * call spread over several lines counts: the arguments are read brace-aware,
 * so `useCategories(\n)` is a finding and `useCategories(\n  undefined,
 * \n  undefined,\n  false,\n)` is not.
 *
 * Modes:
 *   node check-category-scope.mjs                    # report and exit 1
 *   node check-category-scope.mjs --baseline         # only NEW findings fail
 *   node check-category-scope.mjs --write-baseline   # snapshot current
 *   node check-category-scope.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/category-scope-baseline.json
 * The goal is an empty baseline. Each entry is a call whose author knew what
 * it meant and did not write it down.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/category-scope-baseline.json");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isScanned(rel) {
  if (!/\.tsx?$/.test(rel)) return false;
  if (/\.test\.tsx?$/.test(rel)) return false;
  return true;
}

/**
 * The argument text of every `useCategories(...)` call in a file.
 *
 * Read brace- and paren-aware: an argument can itself be a call or an object,
 * and a regex stopping at the first `)` would read half of them as empty.
 * `useScopedCategories` does not match: there is no word boundary before
 * `Categories` there.
 */
export function callArguments(text, name = "useCategories") {
  const out = [];
  const opener = new RegExp(`\\b${name}\\s*\\(`, "g");
  let match;
  while ((match = opener.exec(text)) !== null) {
    const start = opener.lastIndex; // just after "("
    let depth = 1;
    let i = start;
    for (; i < text.length && depth > 0; i++) {
      const char = text[i];
      if (char === "(" || char === "{" || char === "[") depth++;
      else if (char === ")" || char === "}" || char === "]") depth--;
    }
    out.push({ index: match.index, args: text.slice(start, i - 1) });
  }
  return out;
}

/** Calls that name no scope at all. */
export function unscopedIn(rel, source) {
  const text = blankComments(source);
  return callArguments(text)
    .filter(({ args }) => args.trim() === "")
    .map(({ index }) => ({
      file: rel,
      line: text.slice(0, index).split("\n").length,
    }));
}

/** File and line: a bare call is one call, and moving it is not a new one. */
export function findingKey(f) {
  return f.file;
}

export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = findingKey(f);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

export function diffBaseline(findings, baselineCounts) {
  const current = tally(findings);
  const base = new Map(Object.entries(baselineCounts ?? {}));
  const added = [];
  const fixed = [];
  for (const [key, count] of current) {
    const was = base.get(key) ?? 0;
    if (count > was) added.push({ key, was, now: count });
  }
  for (const [key, was] of base) {
    const now = current.get(key) ?? 0;
    if (now < was) fixed.push({ key, was, now });
  }
  return { added, fixed, current };
}

function main() {
  const args = process.argv.slice(2);
  const useBaseline = args.includes("--baseline");
  const writeBaseline = args.includes("--write-baseline");
  const quiet = args.includes("--quiet");

  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const findings = files.flatMap((rel) =>
    unscopedIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          unscoped: Object.fromEntries([...tally(findings)].sort()),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `category-scope baseline written: ${findings.length} bare call(s) → scripts/category-scope-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unscoped
      : {};
  const { added, fixed } = diffBaseline(findings, baseline);

  if (added.length > 0) {
    console.error(
      `\ncategory-scope: ${added.length} NEW bare useCategories() call(s)\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    console.error(
      "\nSay which categories the screen means: `useAllCategories()` when " +
        "the list names rows that already stand somewhere, " +
        "`useScopedCategories()` when the screen offers a picker or a " +
        "filter, or an explicit `excludeModuleContexts` argument for a " +
        "management screen with its own scope.",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `category-scope: ${files.length} file(s) scanned, ${total} bare call(s) (all in the baseline).`,
    );
    if (fixed.length > 0) {
      console.log(
        `✓ ${fixed.length} baseline entr(y/ies) improved — run --write-baseline to refresh.`,
      );
    }
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
