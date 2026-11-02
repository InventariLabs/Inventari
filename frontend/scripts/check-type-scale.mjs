#!/usr/bin/env node
/**
 * check-type-scale.mjs
 *
 * The type scale is 10 / 12 / 14 / 16 / 18 / 20, and each weight has one job.
 *
 * Measured before this gate existed: `font-semibold` covered twelve sizes from
 * 7px to 24px — 613 call sites, 45% of every weight declaration in the app,
 * carrying the page title and a 10px caption alike. With one weight spanning
 * the whole range, hierarchy rested on size and colour alone, and the product
 * read as flat no matter which individual value was adjusted. Twenty-eight
 * places sat below the 10px floor (§2.9), where a unit once rendered "PCS." as
 * "PC…", and thirty-four more used 11px or 13px, which are not steps of
 * anything.
 *
 * Three rules, each mechanical enough to check:
 *
 *   1. `text-[Npx]` is allowed only at 10px — the micro-label token. Every
 *      other size is a Tailwind step.
 *   2. `font-semibold` marks a title, so it may not sit on `text-xs` or
 *      `text-[10px]`, which are label roles.
 *   3. `font-bold` is retired from the interface. A monospace string keeps it:
 *      on a serial number, weight is the only thing separating a code from
 *      prose.
 *
 * Baseline mode matches the repo's other detectors: it fails on findings that
 * are not in `type-scale-baseline.json`, so existing debt does not block a
 * commit while new debt does.
 *
 * Modes:
 *   node check-type-scale.mjs                    # report, exit 1 on findings
 *   node check-type-scale.mjs --baseline         # only findings not baselined
 *   node check-type-scale.mjs --write-baseline   # re-anchor the baseline
 *   node check-type-scale.mjs --quiet            # exit code only
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE = resolve(ROOT, "scripts", "type-scale-baseline.json");

/** The one bracketed size the product is allowed to write by hand. */
const ALLOWED_PX = new Set([10]);
/** Sizes below `text-sm`, where a title weight has no business. */
const LABEL_SIZES = /text-\[10px\]|text-xs(?![a-z-])/;

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
 * Findings in one file, as `{ rule, line, text }`.
 *
 * Line-scoped rather than string-scoped on purpose: a class list is often a
 * template literal with interpolation, and a scan that only understands plain
 * string literals misses exactly the conditional classes most likely to drift.
 */
export function findingsIn(rel, text) {
  const out = [];
  const lines = text.split("\n");

  lines.forEach((line, i) => {
    const at = { file: rel, line: i + 1 };

    for (const m of line.matchAll(/text-\[(\d+)px\]/g)) {
      const px = Number(m[1]);
      if (!ALLOWED_PX.has(px)) {
        out.push({ ...at, rule: "size", text: `text-[${px}px]` });
      }
    }

    // A monospace code is exempt from both weight rules.
    if (line.includes("font-mono")) return;

    // The size and the weight are not always written together: the pagination
    // put `font-semibold` on a span whose `text-xs` sat on the parent, and a
    // line-scoped test walked straight past it. Look up to two lines back for
    // the size when this line names only the weight.
    const nearby = lines.slice(Math.max(0, i - 2), i + 1).join(" ");
    if (line.includes("font-semibold") && LABEL_SIZES.test(nearby)) {
      out.push({ ...at, rule: "weight-small", text: "font-semibold" });
    }
    if (line.includes("font-bold")) {
      out.push({ ...at, rule: "weight-bold", text: "font-bold" });
    }
  });

  return out;
}

const HINTS = {
  size: "Only text-[10px] may be written by hand; use a Tailwind step (§1.2).",
  "weight-small":
    "font-semibold marks a title; a label at text-xs or 10px takes font-medium (§1.2).",
  "weight-bold":
    "font-bold is retired from the interface — font-semibold for a title, and only a font-mono code keeps bold (§1.2).",
};

/** A finding's identity, stable across edits that move it up or down a file. */
const key = (f) => `${f.file}::${f.rule}::${f.text}`;

function main() {
  const args = process.argv.slice(2);
  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const all = files.flatMap((rel) =>
    findingsIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (args.includes("--write-baseline")) {
    const keys = [...new Set(all.map(key))].sort();
    writeFileSync(BASELINE, JSON.stringify(keys, null, 2) + "\n");
    console.log(`type-scale: baseline written with ${keys.length} entr(ies).`);
    process.exit(0);
  }

  let findings = all;
  if (args.includes("--baseline")) {
    const known = new Set(
      existsSync(BASELINE) ? JSON.parse(readFileSync(BASELINE, "utf8")) : [],
    );
    findings = all.filter((f) => !known.has(key(f)));
  }

  if (findings.length > 0) {
    console.error(`type-scale: ${findings.length} finding(s)\n`);
    for (const f of findings.slice(0, 40)) {
      console.error(`  ${f.file}:${f.line}  ${f.text}  — ${HINTS[f.rule]}`);
    }
    if (findings.length > 40) {
      console.error(`  … and ${findings.length - 40} more`);
    }
    process.exit(1);
  }

  if (!args.includes("--quiet")) {
    console.log(`type-scale: all ${files.length} file(s) stay on the scale.`);
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
