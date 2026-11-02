#!/usr/bin/env node
/**
 * check-query-error-read.mjs
 *
 * A failed load must not read as an answer.
 *
 * `const { data = [] } = useThings()` renders "no things" when the request
 * failed: the default is indistinguishable from a real empty list, so the
 * screen tells the user their stock is empty, their rules are gone or their
 * count is zero while the server was merely unreachable. The same holds for
 * `data?.total ?? 0` beside a query whose error nothing reads.
 *
 * The gate is literal. For every `const { … } = use<Something>(…)` (and
 * `const q = use<Something>(…)` read through `q.data`), a finding is a data
 * value that is given an empty default — in the pattern itself (`data = []`)
 * or at a use (`data?.items ?? []`, `data ?? 0`) — while the same pattern
 * never takes `isError`, `error`, `isLoadingError` or `status` and reads it.
 * A query read inline (`useThings().data ?? []`) binds no error at all, so
 * an empty default there is always a finding.
 * "Reads" means a use of the bound name in the same top-level declaration
 * (component or hook), outside string literals and other query patterns:
 * a sibling component, a prose mention or another hook's `isError` does not
 * count. Take `isError` in the pattern that destructures the data and use it.
 *
 * Modes:
 *   node check-query-error-read.mjs                    # report and exit 1
 *   node check-query-error-read.mjs --baseline         # only NEW findings fail
 *   node check-query-error-read.mjs --write-baseline   # snapshot current
 *   node check-query-error-read.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/query-error-read-baseline.json (count per site: file, enclosing declaration, hook and destructuring).
 * The goal is an empty baseline; every fix shrinks it.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/query-error-read-baseline.json");

const EMPTY_DEFAULT = String.raw`(?:\[\]|\{\}|0)(?![\w.])`;

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
  if (/(^|\/)(test|__tests__|types)\//.test(rel)) return false;
  return true;
}

/** Text of a balanced `{…}` starting at the `{` at `open`; null when unclosed. */
function braced(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "{") depth++;
    else if (text[i] === "}" && --depth === 0) return text.slice(open + 1, i);
  }
  return null;
}

/** Index of the `)` closing the `(` at `open`; -1 when unclosed. */
function closingParen(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "(") depth++;
    else if (text[i] === ")" && --depth === 0) return i;
  }
  return -1;
}

/** The name `data` is bound to in a destructuring body, and its default. */
function dataBinding(body) {
  const m = body.match(
    new RegExp(
      String.raw`(?:^|[,\s])data\s*(?::\s*(\w+))?\s*(=\s*${EMPTY_DEFAULT})?`,
    ),
  );
  if (!m) return null;
  return { alias: m[1] ?? "data", defaulted: Boolean(m[2]) };
}

/**
 * The top-level declaration (component, hook, helper) holding `index`:
 * prettier puts every one at column 0. Falls back to the whole file.
 */
function scopeOf(text, index) {
  const decl =
    /^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|const\s+(\w+)\s*(?::[^=\n]+)?=\s*(?:async\s+)?(?:\(|function\b|\w+\s*=>|(?:React\.)?(?:memo|forwardRef)\())/gm;
  let start = 0;
  let end = text.length;
  let name = "<module>";
  let m;
  while ((m = decl.exec(text)) !== null) {
    if (m.index <= index) {
      start = m.index;
      name = m[1] ?? m[2];
    } else {
      end = m.index;
      break;
    }
  }
  return { start, end, name };
}

/** Scope text with string literals and every query pattern blanked out. */
function readableScope(text, scope) {
  return text
    .slice(scope.start, scope.end)
    .replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g, '""')
    .replace(/`[^`]*`/g, (t) =>
      t.replace(/\$\{([^}]*)\}|[^$`]+|\$/g, (m, hole) =>
        hole === undefined ? "" : m,
      ),
    )
    .replace(/\bconst\s*\{[^;]*?\}\s*(?::[^=;]+)?=\s*(?:\(\s*)?use[A-Z]/g, "use");
}

/**
 * Whether an error binding taken in the destructuring is used afterwards:
 * naming `isError` in the pattern is not reading it. `rest` is the readable
 * text of the enclosing declaration.
 */
function errorIsRead(body, rest) {
  const taken = body.replace(/\bdata\b\s*(?::\s*\w+)?/, "");
  const names = /\b(isError|error|isLoadingError|status)\b(?:\s*:\s*(\w+))?/g;
  for (const m of taken.matchAll(names)) {
    const local = m[2] ?? m[1];
    if (new RegExp(String.raw`(?<![.\w])${local}\b`).test(rest)) return true;
  }
  return false;
}

export function unreadErrorsIn(rel, source) {
  const text = blankComments(source);
  const out = [];
  const lineOf = (index) => text.slice(0, index).split("\n").length;

  const pattern = /\bconst\s*\{/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const open = match.index + match[0].length - 1;
    const body = braced(text, open);
    if (body === null) continue;
    const after = text.slice(open + body.length + 2);
    if (!/^\s*(?::[^=]+)?=\s*(?:\(\s*)?use[A-Z]\w*\s*[(<]/.test(after))
      continue;
    const data = dataBinding(body);
    if (!data) continue;
    const scope = scopeOf(text, match.index);
    if (errorIsRead(body, readableScope(text, scope))) continue;
    const alias = data.alias;
    const atUse = new RegExp(
      String.raw`\b${alias}\s*(?:\?\.[\w.?]+|\.[\w.]+)?\s*\?\?\s*${EMPTY_DEFAULT}`,
    ).test(text.slice(scope.start, scope.end));
    if (data.defaulted || atUse) {
      const hook = after.match(/use[A-Z]\w*/)[0];
      out.push({
        file: rel,
        line: lineOf(match.index),
        site: `${scope.name} :: ${hook} ${body.replace(/\s+/g, " ").trim()}`,
      });
    }
  }

  const whole = /\bconst\s+(\w+)\s*=\s*use[A-Z]\w*\s*[(<]/g;
  while ((match = whole.exec(text)) !== null) {
    const name = match[1];
    const scope = scopeOf(text, match.index);
    const scoped = readableScope(text, scope);
    const atUse = new RegExp(
      String.raw`\b${name}\.data\b[\w.?]*\s*\?\?\s*${EMPTY_DEFAULT}`,
    ).test(scoped);
    const reads = new RegExp(
      String.raw`\b${name}\.(isError|error|isLoadingError|status)\b`,
    ).test(scoped);
    if (atUse && !reads) {
      out.push({
        file: rel,
        line: lineOf(match.index),
        site: `${scope.name} :: ${name} = ${match[0].match(/use[A-Z]\w*/)[0]}`,
      });
    }
  }

  const inline = /\buse[A-Z]\w*\s*(?:<[^>()]*>\s*)?\(/g;
  while ((match = inline.exec(text)) !== null) {
    const close = closingParen(text, match.index + match[0].length - 1);
    if (close === -1) continue;
    const read = new RegExp(
      String.raw`^\s*\.data\b(?:\??\.\w+)*\s*\?\?\s*${EMPTY_DEFAULT}`,
    );
    if (!read.test(text.slice(close + 1))) continue;
    const scope = scopeOf(text, match.index);
    out.push({
      file: rel,
      line: lineOf(match.index),
      site: `${scope.name} :: ${match[0].match(/use[A-Z]\w*/)[0]}().data`,
    });
  }
  return out;
}

export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = `${f.file} :: ${f.site}`;
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
    unreadErrorsIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          unread: Object.fromEntries([...tally(findings)].sort()),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `query-error-read baseline written: ${findings.length} site(s) → scripts/query-error-read-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unread
      : {};
  const { added, fixed } = diffBaseline(findings, baseline);

  if (added.length > 0) {
    console.error(
      `\nquery-error-read: ${added.length} NEW unread query error site(s)\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    console.error(
      "\nA query's empty default renders as an answer when the request " +
        "failed. Take `isError` (or `error`) in the same destructuring as " +
        "`data` and show a failed-load state instead of the empty one.",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `query-error-read: ${files.length} file(s) scanned, ${total} site(s) (all in the baseline).`,
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
