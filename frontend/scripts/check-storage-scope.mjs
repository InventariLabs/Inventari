#!/usr/bin/env node
/**
 * check-storage-scope.mjs
 *
 * A screen that asks for a location says which locations it means.
 *
 * `useStorages()` with no argument answers "every location this organization
 * has" — virtual counterparts and other modules' shelves included. That is
 * the right answer for naming a row that already stands somewhere, and the
 * wrong one for a picker: a food document offered all forty locations of the
 * organization, fifteen of them server racks and patch panels, so a crate of
 * milk could be dispatched to a rack. The hook already has every scoped
 * variant a caller needs — `useStorages("equipment")`, `moduleScope`,
 * `excludeModuleContexts`, `usage: "all"`, and `useScopedStorages()` which
 * returns the offering list and the naming list separately, because they are
 * two different questions and one query cannot answer both.
 *
 * So this gate does not decide the scope; it demands that the call state one.
 * A bare `useStorages()` is the finding, whatever the file. There is no
 * exemption list: the module that owns locations has the same reason to say
 * what it means as the one that borrows them, and `useScopedStorages` itself
 * passes because its own calls carry options.
 *
 * The fix is never a suppression — it is one of:
 *   useStorages("equipment")                          a module's own shelves
 *   useStorages(undefined, { moduleScope: "…" })      those plus untagged
 *   useStorages(undefined, { excludeModuleContexts }) the general slice
 *   useStorages(undefined, { usage: "all" })          naming, not offering
 *   useScopedStorages(keepId)                         a general screen's pair
 *
 * The scanner is deliberately literal — a call with an empty argument list —
 * because the cost of guessing is a reader learning to skip the output. A
 * call spread over several lines counts: the arguments are read brace-aware,
 * so `useStorages(\n)` is a finding and `useStorages(\n  undefined,\n  {…},\n)`
 * is not.
 *
 * One place states more than a scope: the warehouse's one-screen stock
 * actions — Receive goods, Issue goods, Move, and the hook behind the last
 * two. They put goods down and take them up, so they are offered what may
 * hold stock and never a place another module claims, whatever the
 * organization says its general lists should mix. A general slice there
 * passed the first rule (it states a scope) while the screens offered server
 * racks for a delivery of laptops. In those files a `useScopedStorages` call
 * names `purpose: "stock"`, and a `useStorages` or `useStoragesTree` call
 * names `excludeModuleContexts: true` — literally, and not behind a
 * condition the policy decides.
 *
 * Modes:
 *   node check-storage-scope.mjs                    # report and exit 1
 *   node check-storage-scope.mjs --baseline         # only NEW findings fail
 *   node check-storage-scope.mjs --write-baseline   # snapshot current
 *   node check-storage-scope.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/storage-scope-baseline.json
 * The goal is an empty baseline. Each entry is a call whose author knew what
 * it meant and did not write it down.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/storage-scope-baseline.json");

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

/** Comments blanked, not removed, so the line number stays true. */
/**
 * The argument text of every `useStorages(...)` call in a file.
 *
 * Read brace- and paren-aware: an argument can itself be a call or an object
 * (`{ moduleScope: pick(x) }`), and a regex stopping at the first `)` would
 * read the scope out of half of them.
 */
export function callArguments(text, name = "useStorages") {
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

/** The warehouse's one-screen stock actions, by the path of the file. */
export function isStockAction(rel) {
  return /^modules\/warehouse\/(pages\/\w+GoodsPage\.tsx|hooks\/useActionDraft\.ts)$/.test(
    rel,
  );
}

/** Calls in a stock action that take the general slice. */
export function generalSliceIn(rel, source) {
  if (!isStockAction(rel)) return [];
  const text = blankComments(source);
  const at = ({ index }) => ({
    file: rel,
    line: text.slice(0, index).split("\n").length,
  });
  // A conditional is the policy deciding after all: the action this rule
  // was written for passed `showModuleData ? undefined : { … true }`.
  const fixed = (args, scope) => scope.test(args) && !args.includes("?");
  const scoped = callArguments(text, "useScopedStorages").filter(
    ({ args }) => !fixed(args, /\bpurpose\s*:\s*["']stock["']/),
  );
  const lists = [
    ...callArguments(text, "useStorages"),
    ...callArguments(text, "useStoragesTree"),
  ].filter(({ args }) => !fixed(args, /\bexcludeModuleContexts\s*:\s*true\b/));
  return [...scoped, ...lists].map(at);
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
  // No baseline: every stock action states the stock slice today, and a new
  // one is born stating it.
  const generalSlice = files.flatMap((rel) =>
    generalSliceIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );
  if (generalSlice.length > 0 && !writeBaseline) {
    console.error(
      `\nstorage-scope: ${generalSlice.length} stock action call(s) take the general slice\n`,
    );
    for (const { file, line } of generalSlice)
      console.error(`  ${file}:${line}`);
    console.error(
      "\nReceive, Issue and Move offer only places that may hold stock: " +
        '`useScopedStorages(keepId, { purpose: "stock" })`, or ' +
        "`excludeModuleContexts: true` on `useStorages` / `useStoragesTree`.",
    );
    process.exit(1);
  }

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
      `storage-scope baseline written: ${findings.length} bare call(s) → scripts/storage-scope-baseline.json`,
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
      `\nstorage-scope: ${added.length} NEW bare useStorages() call(s)\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    console.error(
      "\nSay which locations the screen means: a context tag for a module's " +
        "own shelves, `moduleScope` for those plus the untagged ones, " +
        '`excludeModuleContexts` for the general slice, `usage: "all"` when ' +
        "the list is for naming rather than offering, or `useScopedStorages()` " +
        "which hands a general screen both answers.",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `storage-scope: ${files.length} file(s) scanned, ${total} bare call(s) (all in the baseline).`,
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
