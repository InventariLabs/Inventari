#!/usr/bin/env node
/**
 * check-e2e-catalog-text.mjs
 *
 * An E2E spec selects by what the screen says, and no local gate runs the
 * browser suite. A branch that renames a catalog string therefore leaves the
 * spec waiting for a text nothing renders, and learns it only after the merge.
 * This gate reads the catalog values the branch removed or changed and names
 * every spec line that still spells one of them.
 *
 * English values are searched in every spec and helper, Polish ones in
 * `polish-ui.spec.ts`, the one spec of the project that renders Polish.
 *
 * Only string, template and regular-expression literals are read: comments
 * and identifiers that happen to contain the word select nothing. A string with
 * `{{interpolations}}` or markup is searched by its longest literal fragment,
 * ignoring case and stopping at word boundaries.
 *
 * Not reported:
 *  - a text some catalog of the same language still holds as a value (the
 *    label lives on under another key, or only its interpolation names or its
 *    letter case changed),
 *  - a literal that spells a longer text the catalogs do hold ("Qty per batch"
 *    after "per batch" went),
 *  - a word inside an address or a selector (`/inventory/items`, `#email`), or
 *    a quoted lowercase word on its own where the catalog capitalised it
 *    (`kind: "items"`): the code passes those around, no screen reads them out,
 *  - a test or step title and an `Error` message, which the screen never shows.
 *
 * Runs on the host: it needs git, which the frontend container does not have.
 * The range is the merge base of `--base` (default `origin/dev`) and HEAD to
 * the working tree.
 *
 *   node frontend/scripts/check-e2e-catalog-text.mjs [--base <ref>]
 *
 * Exit 1 on a finding, 2 when the base cannot be read — never a silent pass.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(import.meta.dirname, ".."); // frontend/

/** The one spec rendered in Polish (the `pl-PL` project's `testMatch`). */
const POLISH_SPEC = /polish-ui\.spec\.ts$/;

const LANGUAGES = {
  en: (spec) => !POLISH_SPEC.test(spec),
  pl: (spec) => POLISH_SPEC.test(spec),
};

/** `en` / `pl` for a catalog path relative to `frontend/`, otherwise null. */
function catalogLanguage(path) {
  const match = path.match(
    /^src\/(?:i18n\/locales\/(en|pl)\/[^/]+|modules\/[^/]+\/i18n\/(en|pl))\.json$/,
  );
  return match ? (match[1] ?? match[2]) : null;
}

function flatten(node, prefix = "", out = new Map()) {
  for (const [key, value] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else if (value && typeof value === "object") flatten(value, path, out);
  }
  return out;
}

/** What the screen does not show literally: variables, nesting, tags, breaks. */
const NOT_LITERAL = /\{\{[^}]*\}\}|\$t\([^)]*\)|<\/?\w+\s*\/?>|\n/;

const parts = (value) => value.split(NOT_LITERAL).map((part) => part.trim());

/** A value with its variable names taken out, for "does this text still exist". */
const shape = (value) => parts(value).join("\u0000").toLowerCase();

const longestFragment = (value) =>
  parts(value).reduce(
    (best, part) => (part.length > best.length ? part : best),
    "",
  );

function textPattern(fragment) {
  const escaped = fragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // What may not touch the text: more of the same word, and the punctuation
  // that makes it part of an address, a selector or a key.
  const word = "\\p{L}\\p{N}_\\-";
  const before = /^[\p{L}\p{N}]/u.test(fragment) ? `(?<![${word}/.#@=&?])` : "";
  const after = /[\p{L}\p{N}]$/u.test(fragment)
    ? `(?![${word}/=@]|\\.[\\p{L}\\p{N}])`
    : "";
  return new RegExp(`${before}${escaped}${after}`, "iu");
}

/** A literal handed to one of these names a test or a failure, not the screen. */
const NOT_A_SELECTOR = /(?<![\w.])(?:test(?:\.\w+)*|new\s+Error)\s*\(\s*$/;

/** A template's `${...}` is code; a literal inside it is read on its own. */
const HOLE = /\$\{(?:[^{}]|\{[^{}]*\})*\}/g;

/** Every literal of one spec that can select by text, without its delimiters. */
function literals(source) {
  const spans = [];
  const code = blankComments(source, (start, end) => spans.push([start, end]));
  return spans
    .filter(
      ([start]) =>
        !NOT_A_SELECTOR.test(code.slice(Math.max(0, start - 100), start)),
    )
    .map(([start, end]) => {
      const closing =
        source[start] === "/" ? source.lastIndexOf("/", end - 1) : end - 1;
      let text = source.slice(start + 1, closing);
      if (source[start] === "`")
        text = text.replace(HOLE, (hole) => hole.replace(/[^\n]/g, " "));
      return {
        line: source.slice(0, start).split("\n").length,
        quoted: source[start] !== "/",
        text,
      };
    });
}

/**
 * `/add \(new\)/` and `'Don\'t'` spell the screen's text with escapes;
 * `\b` and `\n` stand between words.
 */
const unescaped = (text) =>
  text.replace(/\\[bnrt]/g, " ").replace(/\\(?=[^A-Za-z0-9])/g, "");

/**
 * The spec lines that spell a text the catalogs no longer hold.
 *
 * @param before  catalogs as they were, `{ path: json }`, changed files only
 * @param after   every catalog as it is now, `{ path: json }`
 * @param specs   `{ path: source }` of the E2E tree
 */
export function findStaleText({ before, after, specs }) {
  const shapes = { en: new Set(), pl: new Set() };
  const fragments = { en: new Set(), pl: new Set() };
  const now = new Map();
  for (const [path, json] of Object.entries(after)) {
    const language = catalogLanguage(path);
    const values = flatten(json);
    now.set(path, values);
    for (const value of values.values()) {
      shapes[language].add(shape(value));
      for (const part of parts(value))
        fragments[language].add(part.toLowerCase());
    }
  }

  const gone = [];
  for (const [path, json] of Object.entries(before)) {
    const language = catalogLanguage(path);
    for (const [key, old] of flatten(json)) {
      const next = now.get(path)?.get(key);
      const fragment = longestFragment(old);
      if (next === old || !/\p{L}{2}/u.test(fragment)) continue;
      if ([old, fragment].some((text) => shapes[language].has(shape(text))))
        continue;
      const lower = fragment.toLowerCase();
      const pattern = textPattern(fragment);
      gone.push({ language, path, key, old, next, fragment, lower, pattern });
    }
  }

  const findings = new Map();
  if (gone.length === 0) return [];
  const held = { en: [...fragments.en], pl: [...fragments.pl] };
  for (const [spec, source] of Object.entries(specs)) {
    const wanted = gone.filter(({ language }) => LANGUAGES[language](spec));
    for (const literal of literals(source)) {
      const text = unescaped(literal.text);
      const lowered = text.toLowerCase();
      // A regex's anchors are not part of the text it asks for.
      const said = lowered.replace(/^\^|\$$/g, "").trim();
      const alone = literal.quoted && !/\s/.test(text);
      for (const gap of wanted) {
        const { language, fragment, lower, pattern } = gap;
        // The cheap test first: a rewording sweep removes hundreds of texts.
        if (!lowered.includes(lower)) continue;
        const match = pattern.exec(text);
        if (!match) continue;
        const [found] = match;
        if (alone && found !== fragment && found === lower) continue;
        const stillShown = held[language].some(
          (part) =>
            part !== lower &&
            part.includes(lower) &&
            (said.includes(part) || (said !== lower && part.includes(said))),
        );
        if (stillShown) continue;
        const above = text.slice(0, match.index).split("\n").length - 1;
        const line = literal.line + above;
        const { old, next, path, key } = gap;
        const id = `${spec}:${line}:${old}`;
        if (!findings.has(id))
          findings.set(id, { spec, line, old, next, path, key });
      }
    }
  }
  return [...findings.values()].sort(
    (a, b) => a.spec.localeCompare(b.spec) || a.line - b.line,
  );
}

function walk(dir, out = []) {
  for (const entry of readdirSync(join(ROOT, dir), { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) walk(path, out);
    else out.push(path);
  }
  return out;
}

function currentCatalogs() {
  const paths = [
    ...walk("src/i18n/locales"),
    ...walk("src/modules").filter((path) => path.includes("/i18n/")),
  ];
  return Object.fromEntries(
    paths
      .filter(catalogLanguage)
      .map((path) => [
        path,
        JSON.parse(readFileSync(join(ROOT, path), "utf8")),
      ]),
  );
}

function git(...args) {
  return execFileSync("git", args, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

/** The exit code of one run. */
function main(argv) {
  const flag = argv.indexOf("--base");
  const base = flag === -1 ? "origin/dev" : argv[flag + 1];
  let before;
  try {
    const from = git("merge-base", base, "HEAD").trim();
    // Files that existed at the base: an added catalog has no old text.
    const changed = git(
      "diff",
      "--name-only",
      "--no-renames",
      "--relative",
      "--diff-filter=MDT",
      from,
      "--",
      "src",
    )
      .split("\n")
      .filter(catalogLanguage);
    before = Object.fromEntries(
      changed.map((path) => [
        path,
        JSON.parse(git("show", `${from}:./${path}`)),
      ]),
    );
  } catch (error) {
    console.error(
      `e2e catalog text: cannot read the changes since ${base}: ${error.stderr?.trim() || error.message}\nFetch it, or name another base with --base <ref>.`,
    );
    return 2;
  }

  const specs = Object.fromEntries(
    walk("tests/e2e")
      .filter((path) => path.endsWith(".ts"))
      .map((path) => [path, readFileSync(join(ROOT, path), "utf8")]),
  );
  const findings = findStaleText({ before, after: currentCatalogs(), specs });

  if (findings.length === 0) {
    console.log(
      `e2e catalog text: no spec spells a string removed since ${base}.`,
    );
    return 0;
  }
  const quote = (value) => JSON.stringify(value);
  console.error(
    `e2e catalog text: ${findings.length} spec line(s) still spell a string the catalogs no longer hold.`,
  );
  for (const { spec, line, old, next, path, key } of findings) {
    console.error(
      `  frontend/${spec}:${line}  ${quote(old)} -> ${next === undefined ? "(removed)" : quote(next)}  [frontend/${path}: ${key}]`,
    );
  }
  console.error(
    "Update each line to what the screen says now, then run that spec on the isolated stack.",
  );
  return 1;
}

if (process.argv[1] && resolve(process.argv[1]) === import.meta.filename) {
  process.exitCode = main(process.argv.slice(2));
}
