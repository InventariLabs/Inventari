#!/usr/bin/env node
/**
 * check-primary-tabs.mjs
 *
 * `ListControlBar`'s `primaryTabs` is the fixed set of ways to look at a
 * list — Active / Archived, one status per tab. A tab set built from network
 * data is a different control wearing the same slot: it paginates, it loads,
 * it empties, and the last one has been removed (the inventory report's
 * storage picker, `...(storages ?? []).map(...)`). Since then the count of
 * such call sites is exactly zero, which is what makes a gate worth having: any new one
 * is a regression, not debt.
 *
 * One rule, mechanical enough to check: inside a `primaryTabs={{ … }}` block,
 * `options` may not be built by spreading a coalesced variable —
 * `...(x ?? []).map(`. Module constants (STATUS_TABS.map) and literals are
 * fine; a value that arrives over the wire is not.
 *
 * Modes:
 *   node check-primary-tabs.mjs           # report, exit 1 on findings
 *   node check-primary-tabs.mjs --quiet   # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
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
  if (/\.test\.tsx?$/.test(rel)) return false;
  return true;
}

/** The banned shape: a spread of a null-coalesced variable, mapped. */
const NETWORK_SPREAD = /\.\.\.\s*\([\s\S]*?\?\?\s*\[\]\s*\)\s*\.map\s*\(/;

/**
 * Findings in one file, as `{ rule, line, text }`.
 *
 * Works on the `primaryTabs={{ … }}` block with a brace count rather than a
 * parser: the gate's job is to catch the one pattern above, and a brace count
 * survives the template literals and `t("…")` calls these blocks actually
 * contain.
 */
export function findingsIn(rel, text) {
  const out = [];

  for (const m of text.matchAll(/primaryTabs\s*=\s*\{/g)) {
    const start = text.indexOf("{", m.index);
    let depth = 0;
    let end = -1;
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    if (end === -1) continue;

    const block = text.slice(start, end + 1);
    const options = block.match(/options\s*:\s*([\s\S]*)/);
    if (!options) continue;

    const bad = options[1].match(NETWORK_SPREAD);
    if (bad) {
      out.push({
        file: rel,
        line: text.slice(0, start).split("\n").length,
        rule: "network-tabs",
        text: bad[0].split("\n")[0].trim(),
      });
    }
  }

  return out;
}

const HINTS = {
  "network-tabs":
    "primaryTabs is a fixed set of views, not a collection from the wire — put network data in search or chips.",
};

function main() {
  const args = process.argv.slice(2);
  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const findings = files.flatMap((rel) =>
    findingsIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (findings.length > 0) {
    console.error(`primary-tabs: ${findings.length} finding(s)\n`);
    for (const f of findings.slice(0, 40)) {
      console.error(`  ${f.file}:${f.line}  ${f.text}  — ${HINTS[f.rule]}`);
    }
    if (findings.length > 40) {
      console.error(`  … and ${findings.length - 40} more`);
    }
    process.exit(1);
  }

  if (!args.includes("--quiet")) {
    console.log(`primary-tabs: all ${files.length} file(s) keep tabs fixed.`);
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
