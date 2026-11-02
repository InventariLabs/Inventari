#!/usr/bin/env node
/**
 * lint-test-assertions.mjs
 *
 * Flags two kinds of test that pass no matter what the product does.
 *
 *   1. A query for a raw i18n key — getByText("common:form.cancel"). The key
 *      is what a component renders when the translation is *missing*, so the
 *      assertion is satisfied both by a working screen and by a broken one.
 * Since the unit suite runs the real i18next, which resolves keys;
 *      any query left matching a key is now asserting a defect.
 *
 *   2. A test body with no assertion and no expectation — no expect(), no
 *      waitFor, no toHaveBeenCalled, no rejects/resolves. It proves the
 *      render did not throw and nothing else, which is rarely what the test
 *      name claims.
 *
 * Usage:
 *   node scripts/lint-test-assertions.mjs           # exit 1 on violations
 *   node scripts/lint-test-assertions.mjs --list    # print and exit 0
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, relative, join } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const SEARCH_DIR = join(ROOT, "src");
const LIST_ONLY = process.argv.includes("--list");

/** Namespaced ("warehouse:actions.x") or dotted ("actions.applyCorrection"). */
const RAW_KEY = /^(?:[a-z_]+:)?[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+)+$/;
/** Dotted strings that are legitimately asserted as text. */
const NOT_A_KEY = /\.(pdf|csv|xlsx?|json|png|jpe?g|webp|svg|txt|zip|ts|tsx)$/i;
/** Same-line comment that suppresses the raw-key finding. */
const ESCAPE_HATCH = "not-an-i18n-key";

/**
 * Testing-library queries whose argument is matched against rendered text.
 *
 * getBy/findBy only — a positive claim that the screen shows something. queryBy
 * is the absence idiom, and there a raw key is legitimate: "if this toggle ever
 * came back it would render as its untranslated key, and it must not be here".
 */
const TEXT_QUERY =
  /\b(?:get|find)(?:All)?By(?:Text|Title|LabelText|PlaceholderText|DisplayValue|AltText)\(\s*"([^"\\\n]+)"/g;

/** getByRole(..., { name: "…" }) — the accessible name is rendered text too. */
const ROLE_NAME_QUERY =
  /\b(?:get|find)(?:All)?ByRole\([^)]*?\bname:\s*"([^"\\\n]+)"/g;

/**
 * Anything that makes a test able to fail. `expect\w*` on purpose: a helper
 * named expectScrollableModal asserts inside, and following it here beats
 * flagging every test that extracted its assertions into one.
 */
const HAS_EXPECTATION = /\b(?:expect\w*|waitFor\w*|assert\w*)\s*\(/;

function collect(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) collect(full, out);
    else if (/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

/**
 * Returns the source of every `it(...)` / `test(...)` body in the file, with
 * the line the block starts on. Brace matching rather than a regex, so nested
 * callbacks do not truncate a body.
 */
function testBodies(source) {
  const bodies = [];
  const opener = /\b(?:it|test)(?:\.each\([\s\S]*?\))?\s*\(/g;
  let match;
  while ((match = opener.exec(source)) !== null) {
    let depth = 1;
    let index = match.index + match[0].length;
    for (; index < source.length && depth > 0; index++) {
      if (source[index] === "(") depth++;
      else if (source[index] === ")") depth--;
    }
    const body = source.slice(match.index, index);
    // Skip declarations without a callback (it.todo("…")).
    if (!/=>|function\s*\(/.test(body)) continue;
    const line = source.slice(0, match.index).split("\n").length;
    const nameMatch = body.match(/^\s*(?:it|test)[^(]*\(\s*["'`]([^"'`]*)/);
    bodies.push({ line, body, name: nameMatch ? nameMatch[1] : "" });
    opener.lastIndex = index;
  }
  return bodies;
}

const rawKeys = [];
const noAssertion = [];

for (const file of collect(SEARCH_DIR)) {
  const source = readFileSync(file, "utf8");
  const rel = relative(ROOT, file);

  for (const pattern of [TEXT_QUERY, ROLE_NAME_QUERY]) {
    let match;
    pattern.lastIndex = 0;
    while ((match = pattern.exec(source)) !== null) {
      const literal = match[1];
      if (!RAW_KEY.test(literal) || NOT_A_KEY.test(literal)) continue;
      const line = source.slice(0, match.index).split("\n").length;
      // Dotted identifiers that are data, not translations — webhook event
      // types, feature flags. Mark them on the line or the one above.
      const lines = source.split("\n");
      const nearby = `${lines[line - 2] ?? ""}\n${lines[line - 1] ?? ""}`;
      if (nearby.includes(ESCAPE_HATCH)) continue;
      rawKeys.push({ file: rel, line, literal });
    }
  }

  for (const { line, body, name } of testBodies(source)) {
    if (!HAS_EXPECTATION.test(body)) {
      noAssertion.push({ file: rel, line, name });
    }
  }
}

if (rawKeys.length) {
  console.log(`\nRaw i18n keys queried as text (${rawKeys.length}):`);
  for (const v of rawKeys) {
    console.log(`  ${v.file}:${v.line}  "${v.literal}"`);
  }
}

if (noAssertion.length) {
  console.log(`\nTest blocks with no assertion (${noAssertion.length}):`);
  for (const v of noAssertion) {
    console.log(`  ${v.file}:${v.line}  ${v.name}`);
  }
}

const total = rawKeys.length + noAssertion.length;
if (!total) {
  console.log("Test assertions: no issues found");
  process.exit(0);
}

console.log(`\n${total} issue(s).`);
process.exit(LIST_ONLY ? 0 : 1);
