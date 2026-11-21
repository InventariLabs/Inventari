#!/usr/bin/env node
/**
 * check-raw-machine-values.mjs
 *
 * Two shapes of one class: a value the machine holds reaches the reader
 * without being put in words or in the reader's format. They come from the
 * 2026-11 QA round, where six passes met the class independently.
 *
 * 1. `dynamic-key` — a translation key built from an id.
 *    AssetTable built `t(\`table.columns.${key}\`)` from the API's column id
 *    `assigned_to` while the catalogue key is `assignedTo`; the Columns menu
 *    printed the raw key in three languages, and no key check could see it,
 *    because the key only exists at run time. A template literal (or a
 *    concatenation) in the key position of `t(` / `tDyn(` / `i18n.t(` is a
 *    finding unless the line above it enumerates what it can produce:
 *
 *        // i18n-keys: name | serial | assignedTo
 *        t(`table.columns.${key}`)
 *
 *    Each listed value is expanded into the key and must exist in every
 *    maintained language's catalogue, so an enumeration that names
 *    `assigned_to` fails the way the menu failed.
 *
 * 2. `raw-number` — a number or a date formatted outside the reader's locale.
 *    DailyNutritionCard printed `13.8 g` for a Polish reader beside `0,0 dni`;
 *    the public attestation page printed `Dec 3, 2026` beside the module's
 *    `3 Dec 2026`. A finding is:
 *      - `.toFixed(` inside a template-literal hole or a JSX expression
 *        (the result is text with the English decimal mark);
 *      - a numeric-looking field (`carbs_g`, `unit_price`, `total_cost`)
 *        interpolated into a template literal that carries other text;
 *      - a numeric-looking field, or a `.toFixed(` result, handed to `t()`
 *        as an interpolation parameter (`t(key, { max: line.quantity })`):
 *        i18next here has no interpolation format, so the number reaches the
 *        sentence in the English decimal mark;
 *      - a numeric-looking field beside text in JSX (`{day.carbs_g} g`);
 *      - `Intl.NumberFormat` / `Intl.DateTimeFormat` / `toLocale*String` with
 *        a literal locale, or none (the browser's, not the app's; reading
 *        the time zone with `.resolvedOptions()` is no format) — the
 *        reader's language is `i18n.language`, and the app's formatters
 *        (`utils/formatters.ts`) are the one place that turns it into a
 *        format.
 *
 * Both are measured against `raw-machine-values-baseline.json`: only NEW
 * findings fail. The goal is an empty baseline.
 *
 * Modes:
 *   node check-raw-machine-values.mjs                   # report, exit 1
 *   node check-raw-machine-values.mjs --baseline        # only NEW fail
 *   node check-raw-machine-values.mjs --write-baseline  # snapshot current
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { maintainedLanguages } from "./maintained-languages.mjs";
import { blankComments } from "./source-text.mjs";

const ROOT = resolve(import.meta.dirname, ".."); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/raw-machine-values-baseline.json");

/** The app's own formatters: the one place a locale becomes a format. */
const FORMATTER_HOMES = new Set([
  "utils/formatters.ts",
  "lib/i18nHelpers.ts",
  "utils/money.ts",
]);

export function isScanned(rel) {
  if (!/\.tsx?$/.test(rel)) return false;
  if (/\.test\.tsx?$/.test(rel) || /\.d\.ts$/.test(rel)) return false;
  if (rel.startsWith("types/") || rel.startsWith("i18n/")) return false;
  return !FORMATTER_HOMES.has(rel);
}

function lineOf(text, index) {
  return text.slice(0, index).split("\n").length;
}

/** The template hole (`${…}`) bodies of the template literal at `start`. */
function templateHoles(text, start) {
  const holes = [];
  let depth = 0;
  let holeStart = -1;
  for (let i = start + 1; i < text.length; i++) {
    const ch = text[i];
    if (depth === 0) {
      if (ch === "\\") i++;
      else if (ch === "`") break;
      else if (ch === "$" && text[i + 1] === "{") {
        depth = 1;
        holeStart = i + 2;
        i++;
      }
    } else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) {
      holes.push({ at: holeStart, body: text.slice(holeStart, i) });
    }
  }
  return holes;
}

/** The end of the template literal that opens at `start`. */
function templateEnd(text, start) {
  let depth = 0;
  for (let i = start + 1; i < text.length; i++) {
    const ch = text[i];
    if (depth === 0) {
      if (ch === "\\") i++;
      else if (ch === "`") return i;
      else if (ch === "$" && text[i + 1] === "{") {
        depth = 1;
        i++;
      }
    } else if (ch === "{") depth++;
    else if (ch === "}") depth--;
  }
  return text.length;
}

const TRANSLATE_CALL = /(?<![\w$.])(?:i18n\.)?(?:t|tDyn|tDynamic)\(\s*/g;
const ENUMERATION = /\/\/\s*i18n-keys:\s*(.+)\s*$/;

/** Template or concatenated keys in the first argument of a translate call. */
export function dynamicKeysIn(source) {
  const text = blankComments(source);
  const lines = source.split("\n");
  const found = [];
  TRANSLATE_CALL.lastIndex = 0;
  let match;
  while ((match = TRANSLATE_CALL.exec(text)) !== null) {
    const at = match.index + match[0].length;
    let template = null;
    if (text[at] === "`") {
      const end = templateEnd(text, at);
      const body = text.slice(at + 1, end);
      if (body.includes("${")) template = body;
    } else if (/^["'][\w:.-]*["']\s*\+/.test(text.slice(at, at + 120))) {
      const concat = text
        .slice(at)
        .match(/^(["'][\w:.-]*["']\s*\+\s*[\w$.?!]+)/);
      if (concat) template = concat[1].replace(/["']\s*\+\s*/, "${") + "}";
    }
    if (template === null) continue;
    const line = lineOf(text, match.index);
    const above = lines[line - 2] ?? "";
    const listed = above.match(ENUMERATION);
    found.push({
      line,
      template: template.replace(/\s+/g, " "),
      enumerated: listed ? listed[1].split("|").map((v) => v.trim()) : null,
    });
  }
  return found;
}

/** Every dotted path under every namespace of one language's catalogues. */
function catalogPaths(language) {
  const paths = new Set();
  const dir = resolve(ROOT, `src/i18n/locales/${language}`);
  const walkJson = (node, prefix) => {
    if (node && typeof node === "object") {
      for (const [key, value] of Object.entries(node)) {
        const path = prefix ? `${prefix}.${key}` : key;
        paths.add(path);
        walkJson(value, path);
      }
    }
  };
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
    walkJson(JSON.parse(readFileSync(resolve(dir, file), "utf8")), "");
  }
  return paths;
}

/** Keys an enumeration produces that some language's catalogue lacks. */
export function missingEnumerated(finding, catalogs) {
  const missing = [];
  const hole = /\$\{[^}]*\}/;
  for (const value of finding.enumerated ?? []) {
    const key = finding.template.replace(hole, value).replace(/^[\w-]+:/, "");
    for (const [language, paths] of catalogs) {
      if (!paths.has(key)) missing.push(`${language}:${key}`);
    }
  }
  return missing;
}

const NUMERIC_FIELD =
  /^[\w$.?]*\.(?:\w+_(?:g|kg|mg|ml|l|qty|quantity|amount|cost|price|pct|percent|total|weight|volume|days|hours|kcal)|(?:price|cost|amount|quantity|qty|weight))$/;

/** The index of the first of `stops` at nesting depth 0, from `from`. */
function topLevel(text, from, stops) {
  let depth = 0;
  for (let i = from; i < text.length; i++) {
    const ch = text[i];
    if (ch === "`") i = templateEnd(text, i);
    else if (ch === '"' || ch === "'") {
      for (i++; i < text.length && text[i] !== ch; i++)
        if (text[i] === "\\") i++;
    } else if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) {
      if (depth === 0) return stops.includes(ch) ? i : -1;
      depth--;
    } else if (depth === 0 && stops.includes(ch)) return i;
  }
  return -1;
}

/**
 * The interpolation parameters of the `t(key, { … })` calls: `[index, value]`
 * for each property whose value is a bare numeric field or a `.toFixed(` text.
 */
function numberParams(text) {
  const found = [];
  TRANSLATE_CALL.lastIndex = 0;
  let match;
  while ((match = TRANSLATE_CALL.exec(text)) !== null) {
    const comma = topLevel(text, match.index + match[0].length, [",", ")"]);
    if (comma < 0 || text[comma] !== ",") continue;
    let at = comma + 1;
    while (/\s/.test(text[at] ?? "")) at++;
    if (text[at] !== "{") continue;
    const close = topLevel(text, at + 1, ["}"]);
    if (close < 0) continue;
    let from = at + 1;
    while (from < close) {
      let end = topLevel(text, from, [",", "}"]);
      if (end < 0 || end > close) end = close;
      const property = text.slice(from, end);
      const value = property.slice(property.indexOf(":") + 1).trim();
      if (
        property.includes(":") &&
        (NUMERIC_FIELD.test(value) || /\.toFixed\(/.test(value))
      )
        found.push(from);
      from = end + 1;
    }
  }
  return found;
}

/** Numbers and dates written without the reader's locale. */
export function rawNumbersIn(source) {
  const text = blankComments(source);
  const found = [];
  const add = (index, what) => found.push({ line: lineOf(text, index), what });

  const fixed = /\.toFixed\(/g;
  let match;
  while ((match = fixed.exec(text)) !== null) {
    const before = text.slice(Math.max(0, match.index - 160), match.index);
    // Wrapped by a parser: the text is turned back into a number.
    if (/(?:Number|parseFloat|String)\(\s*[^;]*$/.test(before)) continue;
    // Result of toFixed is shown only inside a hole or a JSX expression.
    const insideHole = /\$\{[^}`]*$/.test(before);
    const insideJsx =
      /\{\s*[\w$.()?!\s*/+-]*$/.test(before) && />\s*\{/.test(before);
    if (insideHole || insideJsx) add(match.index, "toFixed");
  }

  const literalLocale =
    /Intl\.(?:NumberFormat|DateTimeFormat)\(\s*(?:["'`]|\)(?!\s*\.resolvedOptions)|undefined\b)|toLocale(?:Date|Time)?String\(\s*(?:["'`]|\)|undefined\b)/g;
  while ((match = literalLocale.exec(text)) !== null) {
    add(match.index, "locale");
  }

  for (const index of numberParams(text)) add(index, "t-param");

  // `{day.carbs_g} g`: a numeric field printed next to text in JSX.
  const jsxText = />([^<>{}]*)\{\s*([\w$.?]+)\s*\}([^<>{}]*)</g;
  while ((match = jsxText.exec(text)) !== null) {
    if (NUMERIC_FIELD.test(match[2]) && (match[1].trim() || match[3].trim()))
      add(match.index, "jsx-number");
    jsxText.lastIndex = match.index + 1;
  }

  const template = /`/g;
  while ((match = template.exec(text)) !== null) {
    const end = templateEnd(text, match.index);
    const body = text.slice(match.index + 1, end);
    if (body.includes("${")) {
      const literal = body.replace(/\$\{[^}]*\}/g, "");
      if (/\S/.test(literal)) {
        for (const hole of templateHoles(text, match.index)) {
          if (NUMERIC_FIELD.test(hole.body.trim())) add(hole.at, "number");
        }
      }
    }
    template.lastIndex = end + 1;
  }
  return found;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function tally(entries) {
  const counts = {};
  for (const key of entries) counts[key] = (counts[key] ?? 0) + 1;
  return Object.fromEntries(Object.entries(counts).sort());
}

export function diffBaseline(current, baseline) {
  const added = [];
  for (const [key, now] of Object.entries(current)) {
    const was = baseline[key] ?? 0;
    if (now > was) added.push({ key, was, now });
  }
  return added;
}

function scanTree() {
  const dynamic = [];
  const numbers = [];
  const bad = [];
  const catalogs = new Map(
    maintainedLanguages(ROOT).map((l) => [l, catalogPaths(l)]),
  );
  for (const file of walk(SRC)) {
    const rel = relative(SRC, file).split("\\").join("/");
    if (!isScanned(rel)) continue;
    const source = readFileSync(file, "utf8");
    for (const f of dynamicKeysIn(source)) {
      if (f.enumerated === null) dynamic.push(`${rel}::${f.template}`);
      else {
        for (const miss of missingEnumerated(f, catalogs))
          bad.push(
            `${rel}:${f.line} enumerates a key no catalogue has: ${miss}`,
          );
      }
    }
    for (const f of rawNumbersIn(source)) numbers.push(`${rel}::${f.what}`);
  }
  return { dynamic: tally(dynamic), numbers: tally(numbers), bad };
}

function main() {
  const args = process.argv.slice(2);
  const { dynamic, numbers, bad } = scanTree();

  if (args.includes("--write-baseline")) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify({ dynamicKeys: dynamic, rawNumbers: numbers }, null, 2) +
        "\n",
    );
    console.log(
      `raw-machine-values baseline written: ${Object.keys(dynamic).length} dynamic key site(s), ${Object.keys(numbers).length} raw number site(s)`,
    );
    process.exit(0);
  }

  const baseline =
    args.includes("--baseline") && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
      : {};
  const newDynamic = diffBaseline(dynamic, baseline.dynamicKeys ?? {});
  const newNumbers = diffBaseline(numbers, baseline.rawNumbers ?? {});

  if (bad.length + newDynamic.length + newNumbers.length > 0) {
    for (const line of bad) console.error(`  ${line}`);
    if (newDynamic.length > 0) {
      console.error(
        `\nraw-machine-values: ${newDynamic.length} NEW key(s) built from an id\n`,
      );
      for (const { key } of newDynamic) console.error(`  ${key}`);
      console.error(
        "\nList what the key can produce on the line above — `// i18n-keys: a | b` —" +
          "\nso each is checked against every catalogue, or look the id up in a map.",
      );
    }
    if (newNumbers.length > 0) {
      console.error(
        `\nraw-machine-values: ${newNumbers.length} NEW number/date outside the reader's locale\n`,
      );
      for (const { key } of newNumbers) console.error(`  ${key}`);
      console.error(
        "\nUse the app's formatters (utils/formatters.ts: formatQuantityLocale, formatDate, …)" +
          "\ninstead of toFixed, a literal locale or a bare numeric field in a sentence.",
      );
    }
    process.exit(1);
  }
  console.log("raw-machine-values: no finding beyond the baseline.");
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
