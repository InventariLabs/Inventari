#!/usr/bin/env node
/**
 * check-plural-counts.mjs
 *
 * A number is never pasted next to a translated noun.
 *
 * `${locationCount} ${t("locations:locations")}` gives i18next no `count`, so
 * it never selects a plural form. English survives this for every value but
 * one; Polish, Czech, Russian and Arabic do not, and the screen that carried
 * the pattern read "1 lokalizacje" one line above a correctly inflected
 * "0 produktów". The same sentence written as a hand rule (`n === 1 ? a : b`)
 * is one language's grammar compiled into a component.
 *
 * The fix is always the same shape: one key with plural forms, called as
 * `t("key", { count })`, and the number interpolated inside the translation.
 *
 * Scanned: a template literal in which an expression that names a count --
 * `somethingCount`, `xs.length`, `total` -- is followed by a space and a
 * `t(...)` call. Ratios (`{picked}/{total} {t("progress")}`) are left alone:
 * the label after them is not the noun being counted.
 *
 * Modes:
 *   node check-plural-counts.mjs             # report and exit 1 on findings
 *   node check-plural-counts.mjs --quiet     # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");

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
  return !/\.test\.tsx?$/.test(rel);
}

/** An expression that holds a number by its name alone. */
const COUNTING =
  /(?:^|[^\w$])(?:\w[\w$.?[\]()]*\.length|\w*(?:C|c)ount|total\w*|\w+Total)$/;

/** `${<expression>} ${t(...)}`, the ternary form of the second one included. */
const PASTED = /\$\{([^{}]*)\}\s+\$\{\s*([^{}]*\?[^{}]*)?t\(/g;

/**
 * `{<expression>} {t(...)}` in JSX — the same paste written with braces.
 *
 * The scanner read template literals only, so the defect went on living one
 * brace form away: `{totalRows} {t("warehouse:import.rows")}` renders
 * "1 wierszy", and the same shape two lines below renders "1 błędów", while
 * the gate reported a clean tree. A count, a space and a translated noun with
 * no `count` for i18next to select a form with is the same statement in both
 * spellings.
 */
const PASTED_JSX = /\{([^{}]+)\}[ \t]*\{?t\(/g;

/** The key the `t(` after a paste is called with, when it is a plain string. */
const CALLED_KEY = /^\s*(["'])([^"']+)\1/;

/** A unit symbol, not a noun: "szt." reads the same after 1 and after 5. */
const UNIT_SYMBOL = /(?:^|:)(?:units)\./;

/**
 * A hand-written plural rule, whatever the count is called.
 *
 * `${n} ${n === 1 ? t("location") : t("locations")}` is the defect stated
 * outright, so it is reported without asking whether `n` reads as a number.
 */
const HAND_RULE = /===?\s*1\s*\?/;

export function pastedCountsIn(rel, text) {
  const findings = [];
  let match;
  PASTED.lastIndex = 0;
  while ((match = PASTED.exec(text)) !== null) {
    const expression = match[1].trim();
    const selector = match[2] ?? "";
    if (!COUNTING.test(expression) && !HAND_RULE.test(selector)) continue;
    const line = text.slice(0, match.index).split("\n").length;
    findings.push({ file: rel, line, expression });
  }

  PASTED_JSX.lastIndex = 0;
  while ((match = PASTED_JSX.exec(text)) !== null) {
    const expression = match[1].trim();
    if (!COUNTING.test(expression)) continue;
    const key = CALLED_KEY.exec(text.slice(match.index + match[0].length))?.[2];
    // "szt." is a symbol: it has one form in every language.
    if (key && UNIT_SYMBOL.test(key)) continue;
    // `{picked}/{total} {t("progress")}` is a ratio — the word after it is
    // not the noun being counted, and the checker already leaves the
    // template-literal spelling of this shape alone.
    const before = text.slice(0, match.index).replace(/\s+$/, "");
    if (before.endsWith("/")) continue;
    const line = text.slice(0, match.index).split("\n").length;
    findings.push({
      file: rel,
      line,
      expression: `{${expression}}`,
      jsx: true,
    });
  }
  return findings;
}

function main() {
  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const findings = files.flatMap((rel) =>
    pastedCountsIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (findings.length > 0) {
    console.error(
      `plural-counts: ${findings.length} count(s) pasted next to a translated noun\n`,
    );
    for (const f of findings) {
      const shape = f.jsx
        ? `${f.expression} {t(...)}`
        : `\${${f.expression}} \${t(...)}`;
      console.error(`  ${f.file}:${f.line}  ${shape}`);
    }
    console.error(
      "\nGive the key plural forms (key_one / key_other, plus _few and _many " +
        'in pl) and call it as t("key", { count }); i18next selects the form ' +
        "and interpolates the number.",
    );
    process.exit(1);
  }

  if (!process.argv.includes("--quiet")) {
    console.log(
      `plural-counts: all ${files.length} file(s) inflect their counts.`,
    );
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
