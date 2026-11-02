#!/usr/bin/env node
/**
 * check-field-names.mjs
 *
 * Every form control says what it is for.
 *
 * `check-dialog-names` guards the window; this guards what is inside it. A
 * control with no accessible name is announced as "edit text" and nothing
 * else, so a reader using a screen reader is told a value is required without
 * being told what value. The visible text sitting beside the field does not
 * help: a `<p className="uppercase">NAME</p>` is a paragraph, and nothing
 * connects it to the input.
 *
 * This gate exists because the class kept coming back one instance at a time.
 * It was found as four fields, then sixteen, then twenty-three across six
 * modules — every fix named the file it was found in, so the next review
 * found the next file. The point here is that naming instances never emptied the class, and a
 * scanner does.
 *
 * A control passes when its opening tag carries one of:
 *   - `label`, `aria-label`, `aria-labelledby`, `srLabel` (the shared
 *     primitives turn `label` into a real `<label htmlFor>`);
 *   - `id={X}` where the same file wires `htmlFor={X}` — the shape a field
 *     renderer uses when the label and the control are separate elements;
 *   - a spread (`{...props}`), because what it carries cannot be read here;
 *   - a wrapping `<label>` element, which is how the checkbox and toggle
 *     patterns name themselves.
 *
 * Hidden inputs are out of scope: `type="hidden"` and the file input parked
 * behind a styled button (`className="hidden"`) are not controls a reader
 * reaches.
 *
 * Three shapes broke earlier versions of this scanner, and each is pinned by
 * a test:
 *   - `<select>` mentioned in a docstring counted as a control, so comments
 *     are blanked before scanning (blanked, not removed, to keep line
 *     numbers true);
 *   - `id={labelId}` with `<label htmlFor={labelId}>` three lines above read
 *     as unnamed — the id/htmlFor pair is evidence, and it applies to the
 *     wrapped primitives as much as to raw HTML;
 *   - a prop value containing `>` (`max={a > b ? a : b}`) cut the tag in
 *     half, so the tag is read brace-aware, the way `check-dialog-names`
 *     reads a `<Sheet>`.
 *
 * Modes:
 *   node check-field-names.mjs                    # report and exit 1
 *   node check-field-names.mjs --baseline         # only NEW findings fail
 *   node check-field-names.mjs --write-baseline   # snapshot current
 *   node check-field-names.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/field-names-baseline.json
 * The goal is an empty baseline. An entry is a field waiting for a name, not
 * a field excused from having one — give it `label={t(...)}` and drop the
 * line.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/field-names-baseline.json");

/**
 * The controls this gate reads.
 *
 * The four shared primitives take a `label` prop and build the
 * `<label htmlFor>` themselves — a call site that omits it is the whole
 * defect. The three HTML elements are scanned too, because the primitives are
 * not the only way a field gets on screen: the combobox's own search input is
 * a bare `<input>` inside `components/ui`, and it reaches nineteen screens.
 */
export const WRAPPED_CONTROLS = [
  "Input",
  "Textarea",
  "NativeSelect",
  "QuantityInput",
];
export const RAW_CONTROLS = ["input", "textarea", "select"];

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isScanned(rel) {
  if (!rel.endsWith(".tsx")) return false;
  if (/\.test\.tsx$/.test(rel)) return false;
  return true;
}

/**
 * Comments blanked, not removed: the finding carries a line number, and a
 * scanner that deletes text reports the wrong one.
 */
/**
 * The opening tags of one control in a file, with their offsets.
 *
 * Brace-aware, because a prop value can hold a `>` and a regex stopping at
 * the first one reads half a tag and misses the name in the other half.
 */
export function controlTags(text, name) {
  const tags = [];
  const opener = new RegExp(`<${name}(?=[\\s/>])`, "g");
  let match;
  while ((match = opener.exec(text)) !== null) {
    let depth = 0;
    let i = match.index;
    for (; i < text.length; i++) {
      const char = text[i];
      if (char === "{") depth++;
      else if (char === "}") depth--;
      else if (char === ">" && depth === 0) break;
    }
    tags.push({ index: match.index, tag: text.slice(match.index, i + 1) });
  }
  return tags;
}

const NAMED = /\b(?:label|aria-label|aria-labelledby|srLabel)\s*=|\{\.\.\./;
const HIDDEN =
  /type\s*=\s*["'{]?\s*hidden|className\s*=\s*["'][^"']*\bhidden\b/;

/** `id={X}` on the tag and `htmlFor={X}` anywhere in the same file. */
export function labelledById(tag, text) {
  const id =
    tag.match(/\bid=\{([^}]+)\}/)?.[1] ?? tag.match(/\bid="([^"]+)"/)?.[1];
  if (!id) return false;
  const key = id.trim();
  return text.includes(`htmlFor={${key}}`) || text.includes(`htmlFor="${key}"`);
}

/** The control sits inside a `<label>` element, which names it. */
export function insideLabel(text, index) {
  const before = text.slice(0, index);
  const open = before.lastIndexOf("<label");
  if (open === -1) return false;
  return open > before.lastIndexOf("</label>");
}

/** The unnamed controls of one file. */
export function unnamedIn(rel, source) {
  const text = blankComments(source);
  const findings = [];
  for (const name of [...WRAPPED_CONTROLS, ...RAW_CONTROLS]) {
    for (const { index, tag } of controlTags(text, name)) {
      if (NAMED.test(tag)) continue;
      if (HIDDEN.test(tag)) continue;
      if (labelledById(tag, text)) continue;
      if (insideLabel(text, index)) continue;
      findings.push({
        file: rel,
        line: text.slice(0, index).split("\n").length,
        control: name,
      });
    }
  }
  return findings;
}

/**
 * The baseline key.
 *
 * File and control, without the line number: a field that keeps its name
 * missing while the lines above it move is the same finding, and a key that
 * counted lines would turn every unrelated edit into a new one. Several
 * unnamed controls of the same kind in one file collapse to one key, and the
 * count is carried beside it so the gate still sees a new one appear.
 */
export function findingKey(f) {
  return `${f.file}  <${f.control}>`;
}

export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = findingKey(f);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

/**
 * Only what the baseline does not already hold fails: a key it never saw, or
 * a key whose count grew. Keys that dropped are reported so the snapshot gets
 * refreshed rather than quietly drifting.
 */
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
    unnamedIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          unnamed: Object.fromEntries([...tally(findings)].sort()),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `field-names baseline written: ${findings.length} control(s) → scripts/field-names-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unnamed
      : {};
  const { added, fixed } = diffBaseline(findings, baseline);

  if (added.length > 0) {
    console.error(
      `\nfield-names: ${added.length} NEW form control(s) with no accessible name\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    console.error(
      "\nGive the control a name: `label={t(...)}` on the shared primitive, " +
        "or `aria-label` where the design shows no label. A placeholder is " +
        "not a name — it disappears on the first keystroke, and a screen " +
        "reader may never announce it.",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `field-names: ${files.length} file(s) scanned, ${total} control(s) still unnamed (all in the baseline).`,
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
