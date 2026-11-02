#!/usr/bin/env node
/**
 * check-api-types-mirror.mjs
 *
 * A type that keeps a backend schema's name must be an alias of it, never a
 * copy of its fields.
 *
 * `check-mirrored-types` answers a different question: it compares the
 * interfaces that opted in with `@mirrors`, field by field. Opting in is
 * voluntary, so it says nothing about the 180-odd declarations that never
 * mention the wire at all and sit under exactly the names the wire uses. Two
 * names, two shapes, one of them wrong, and `tsc` green over both — which is
 * how `DocumentLine.quantity` came to be `number` while the backend sent a
 * Decimal as text, and `Category.category_type` three food values while the
 * backend typed a plain string.
 *
 * This gate closes that door by construction: a declaration whose name is a
 * key of `components["schemas"]` is either
 *
 *     export type Item = components["schemas"]["Item"];
 *
 * or a finding. Nothing in between. An alias cannot drift, and a hand-written
 * body can only be kept honest by someone re-reading the schema, which is the
 * work this exists to stop expecting of people.
 *
 * The names that are NOT schemas — `ItemProps`, `UseItemsState`, a form's own
 * working shape — are untouched here: they carry no schema name, so they are
 * never compared with one. That is the whole of what "UI-only types stay
 * hand-written" means at this gate's altitude.
 *
 * The scan reads every top-level declaration, exported or not: a private
 * copy under a schema's name drifts exactly like an exported one, and
 * `tsc` is as silent over it.
 *
 * Baseline: frontend/scripts/api-types-mirror-baseline.txt, one `path::Name`
 * per line. It is a list of copies that already existed, sorted so that two
 * subtasks converting their own files delete their own lines and merge
 * without conflict. `--write-baseline` is the only writer; a plain run fails
 * on a key the file does not hold yet.
 *
 * Modes:
 *   node check-api-types-mirror.mjs                    # every finding fails
 *   node check-api-types-mirror.mjs --baseline         # only NEW findings fail
 *   node check-api-types-mirror.mjs --write-baseline   # snapshot current
 *   node check-api-types-mirror.mjs --quiet            # exit code only
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const GENERATED = resolve(SRC, "types/api-generated.ts");
const BASELINE_PATH = resolve(ROOT, "scripts/api-types-mirror-baseline.txt");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/**
 * Which files this gate reads.
 *
 * Tests are excluded on purpose: a fixture that plants an interface under a
 * schema's name is the test doing its job, and baselining it would teach the
 * gate that test code is where copies live.
 */
export function isScanned(rel) {
  if (!rel.endsWith(".ts") && !rel.endsWith(".tsx")) return false;
  if (rel === "types/api-generated.ts") return false;
  if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(rel)) return false;
  return true;
}

/**
 * The keys of `components["schemas"]`.
 *
 * Scoped to the `schemas: {` block first: the eight-space level repeats
 * outside it, and inside an operation the `parameters: {`, `requestBody: {`
 * and `responses: {` members sit at exactly that indentation — watching them
 * as schema names would fail a screen that declares its own `Responses`. The
 * narrower indentation is what keeps the nested object members of a schema —
 * twelve spaces — and the `schemas: {` line itself out of the set;
 * `check-mirrored-types` lost an afternoon to "Category" matching "ByCategory"
 * the other way round.
 *
 * Within the block every eight-space line is a key, whatever its value: an
 * object schema (`Name: {`), a named union (`Name: "a" | "b"`) and a quoted
 * name for what is not an identifier (`"X-Input": {`) all count. A union is a
 * declaration under a schema's name exactly like an object is, and a gate that
 * watched only the objects left `StockTakeStatus`, `DocumentLineStatus`,
 * `LlmProvider` and `LlmCapability` as hand-written copies on the day it was
 * written.
 */
export function schemaNames(generatedSource) {
  const names = new Set();
  const start = generatedSource.search(/^ {4}schemas: \{$/m);
  if (start === -1) return names;
  const block = generatedSource.slice(start);
  const end = block.search(/^ {4}\};$/m);
  const scoped = end === -1 ? block : block.slice(0, end);
  for (const match of scoped.matchAll(/^ {8}(?:"([^"]+)"|([A-Za-z0-9_$]+)):/gm)) {
    names.add(match[1] ?? match[2]);
  }
  return names;
}

/** Every top-level `interface` / `type` declaration, exported or not, with its line number. */
export function declarations(text) {
  const found = [];
  const pattern = /^(?:export\s+)?(?:declare\s+)?(interface|type)\s+([A-Za-z0-9_$]+)/gm;
  for (const match of text.matchAll(pattern)) {
    found.push({
      kind: match[1],
      name: match[2],
      index: match.index,
      line: text.slice(0, match.index).split("\n").length,
    });
  }
  return found;
}

/**
 * The right-hand side of a `type X = …` declaration, read to the `;` that
 * closes it rather than to the first one on the line: a union or an object
 * body carries semicolons of its own, and stopping there would read a
 * fragment and call it an alias.
 */
export function rightHandSide(text, from) {
  let depth = 0;
  let eq = -1;
  for (let i = from; i < text.length; i += 1) {
    const char = text[i];
    // `;` closes the alias and `}` closes whatever block holds it — a type
    // alias written without a semicolon must not swallow the file after it.
    if (depth === 0 && eq >= 0 && (char === ";" || char === "}")) {
      return text.slice(eq + 1, i);
    }
    if (depth === 0 && eq >= 0 && text.startsWith("export ", i)) {
      return text.slice(eq + 1, i);
    }
    if ("([{<".includes(char)) {
      depth += 1;
      continue;
    }
    if (")]}>".includes(char)) {
      // The `>` of `=>` closes no type parameter list, and the depth never
      // goes below zero: a closer with nothing open must not bury the rest
      // of the declaration where a `;` can no longer end it.
      if (!(char === ">" && text[i - 1] === "=") && depth > 0) depth -= 1;
      continue;
    }
    if (char === "=" && eq < 0 && depth === 0) {
      // The FIRST `=` at depth zero opens the alias; a default type
      // parameter sits inside `<…>`, so it is never depth zero.
      eq = i;
    }
  }
  return eq >= 0 ? text.slice(eq + 1) : "";
}

/**
 * The schema an alias points at, or null when it is not an alias at all.
 *
 * An alias is the bare reference — nothing wrapped around it. `Pick<…>`,
 * `Partial<…>` and `… | null` are derived from a schema, and derived shapes
 * can still drift from it (a wrapper is a decision about the shape, taken in
 * the frontend, where the schema cannot argue back), so they are findings.
 * A reference to a DIFFERENT schema under this name is also a finding: two
 * things called `Item` that mean different things is the defect this gate
 * exists for, not an escape from it.
 */
export function aliasTarget(rhs) {
  const match = /^\s*components\s*\[\s*(['"])schemas\1\s*\]\s*\[\s*(['"])([^'"]+)\2\s*\]\s*$/.exec(
    rhs,
  );
  return match ? match[3] : null;
}

/** The reason a declaration is not an alias of its own schema, or null. */
export function whyNotAlias(name, kind, rhs) {
  if (kind === "interface") return "a hand-written interface";
  const target = aliasTarget(rhs);
  if (target === name) return null;
  const reference = rhs.match(
    /components\s*\[\s*(['"])schemas\1\s*\]\s*\[\s*(['"])([^'"]+)\2\s*\]/,
  );
  if (reference) {
    return reference[3] === name
      ? "derived from its schema, not an alias of it"
      : `an alias of "${reference[3]}", not of "${name}"`;
  }
  return "a hand-written type";
}

/**
 * The suffixes the backend puts on a schema whose bare name the frontend then
 * takes for its own copy: `AiConnection` for `AiConnectionDTO`.
 */
export const SHADOW_SUFFIXES = ["DTO", "Response", "Out", "Read", "Schema"];

/** The schemas a declaration shadows under a suffix: `AiConnection` -> `AiConnectionDTO`. */
export function shadowedSchemas(name, schemas) {
  return SHADOW_SUFFIXES.map((suffix) => `${name}${suffix}`).filter((key) => schemas.has(key));
}

/**
 * The operands of `A & B | C` at depth zero, looking through parentheses that
 * wrap a whole operand: `({ id: number })` is the object body it wraps.
 */
export function topLevelOperands(rhs) {
  const text = rhs.trim();
  const operands = [];
  let depth = 0;
  let quote = null;
  let from = 0;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quote) {
      if (char === quote && text[i - 1] !== "\\") quote = null;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") quote = char;
    else if ("([{<".includes(char)) depth += 1;
    else if (")]}>".includes(char)) {
      if (!(char === ">" && text[i - 1] === "=") && depth > 0) depth -= 1;
    } else if ((char === "&" || char === "|") && depth === 0) {
      operands.push(text.slice(from, i));
      from = i + 1;
    }
  }
  operands.push(text.slice(from));
  return operands.flatMap((operand) => unwrapped(operand.trim()));
}

/** The operands inside `( … )` when the first `(` closes at the last character. */
function unwrapped(operand) {
  if (!operand.startsWith("(") || !operand.endsWith(")")) return [operand];
  let depth = 0;
  for (let i = 0; i < operand.length; i += 1) {
    if (operand[i] === "(") depth += 1;
    else if (operand[i] === ")") depth -= 1;
    if (depth === 0 && i < operand.length - 1) return [operand];
  }
  return topLevelOperands(operand.slice(1, -1));
}

/**
 * An operand with every `{ … }` object body blanked: a schema named inside
 * `Array<{ x: Schemas["A"] }>` sits in hand-written fields and derives nothing.
 */
function outsideObjectBodies(operand) {
  let out = "";
  let depth = 0;
  for (const char of operand) {
    if (char === "{") depth += 1;
    else if (char === "}" && depth > 0) depth -= 1;
    else if (depth === 0) out += char;
  }
  return out;
}

/**
 * Why a declaration that shadows `AiConnectionDTO` as `AiConnection` is not
 * measured, or null when it is.
 *
 * Measured means one of two: a type with an operand that is not an object
 * body of its own and names a generated schema — through `components`, or by
 * the shadowed key itself in a local alias (`Schemas["AiConnectionDTO"]`,
 * `Omit<AiConnectionDTO, …>`); the bare alias, `Pick`/`Omit` and an
 * intersection are all that, and the difference is stated beside them. Fields
 * written by hand beside it (an object body, also one inside a generic) must
 * sit beside the shadowed key itself, so `Item & { … }` under the name
 * `Widget` is not measured against `WidgetDTO` — or an interface whose doc comment carries `@mirrors` for one, which
 * `check-mirrored-types` then compares field by field. Anything else is a
 * second set of fields under a name the wire almost uses — a schema
 * mentioned inside the body of an object type, or not at all, derives
 * nothing.
 */
export function whyNotMeasured(decl, shadowed, rhs, doc) {
  if (decl.kind === "type") {
    const namesShadowed = (text) =>
      shadowed.some((key) => new RegExp(`\\b${key}\\b`).test(text));
    const operands = topLevelOperands(rhs);
    const derived = operands
      .map(outsideObjectBodies)
      .filter(
        (outside) =>
          /components\s*\[\s*(['"])schemas\1\s*\]\s*\[/.test(outside) ||
          namesShadowed(outside),
      );
    const handWritten = operands.some((operand) => operand.includes("{"));
    const measured =
      derived.length > 0 && (!handWritten || derived.some(namesShadowed));
    return measured ? null : "a hand-written type under a schema's name";
  }
  const mirrored = [...doc.matchAll(/@mirrors\s+components\[\s*"schemas"\s*\]\[\s*"([^"]+)"\s*\]/g)].map(
    (m) => m[1],
  );
  return mirrored.some((key) => shadowed.includes(key))
    ? null
    : "a hand-written interface under a schema's name, without @mirrors";
}

/** The findings of one file, keyed for the baseline as `path::Name`. */
export function findingsIn(rel, source, schemas) {
  const text = blankComments(source);
  const findings = [];
  for (const decl of declarations(text)) {
    let reason = null;
    if (schemas.has(decl.name)) {
      reason =
        decl.kind === "type"
          ? whyNotAlias(decl.name, decl.kind, rightHandSide(text, decl.index))
          : whyNotAlias(decl.name, decl.kind, "");
    } else {
      const shadowed = shadowedSchemas(decl.name, schemas);
      if (shadowed.length === 0) continue;
      // Blanking keeps offsets, so the comment `text` lost is still at the
      // same place in `source`.
      reason = whyNotMeasured(
        decl,
        shadowed,
        decl.kind === "type" ? rightHandSide(text, decl.index) : "",
        docAbove(source, decl.index),
      );
    }
    if (reason === null) continue;
    findings.push({ path: rel, name: decl.name, line: decl.line, reason });
  }
  return findings;
}

/** The doc comment sitting directly above offset `index`, or "". */
function docAbove(source, index) {
  const before = source.slice(0, index).trimEnd();
  if (!before.endsWith("*/")) return "";
  const open = before.lastIndexOf("/**");
  return open === -1 ? "" : before.slice(open);
}

export function findingKey(finding) {
  return `${finding.path}::${finding.name}`;
}

/**
 * Sorted by path, then by name. The lines are what a parallel subtask
 * deletes — one file's worth of them — so the order has to be the order the
 * file is written in, or two branches touching different lines of an
 * unsorted file disagree about where they end.
 */
export function baselineLines(findings) {
  return [...new Set(findings.map(findingKey))].sort();
}

/** Keys the run has that the baseline does not, and the reverse. */
export function diffBaseline(lines, baseline) {
  const now = new Set(lines);
  const was = new Set(baseline);
  return {
    added: [...now].filter((key) => !was.has(key)),
    fixed: [...was].filter((key) => !now.has(key)),
  };
}

function main() {
  const args = process.argv.slice(2);
  const useBaseline = args.includes("--baseline");
  const writeBaseline = args.includes("--write-baseline");
  const quiet = args.includes("--quiet");

  const schemas = schemaNames(readFileSync(GENERATED, "utf8"));
  const findings = walk(SRC)
    .map((file) => relative(ROOT, file).split("\\").join("/"))
    .filter(isScanned)
    .flatMap((rel) => findingsIn(rel, readFileSync(resolve(ROOT, rel), "utf8"), schemas));

  const lines = baselineLines(findings);

  if (writeBaseline) {
    writeFileSync(BASELINE_PATH, `${lines.join("\n")}\n`);
    console.log(
      `api-types-mirror baseline written: ${lines.length} hand-written ` +
        `copy/copies of a backend schema → scripts/api-types-mirror-baseline.txt`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? readFileSync(BASELINE_PATH, "utf8").split("\n").filter((line) => line !== "")
      : [];
  const { added, fixed } = diffBaseline(lines, baseline);

  if (added.length > 0) {
    console.error(
      `\napi-types-mirror: ${added.length} hand-written type(s) keeping the ` +
        `name of a backend schema\n`,
    );
    for (const key of added) {
      const finding = findings.find((f) => findingKey(f) === key);
      console.error(`  ${key}  (${finding?.reason ?? "not an alias"})`);
    }
    console.error(
      "\nAlias it instead — nothing that can drift:\n" +
        '    export type Name = components["schemas"]["Name"];\n' +
        "A type that is not a copy of a schema (Props, State, a form's own\n" +
        "shape) does not belong under a schema's name; rename it. See\n" +
        "frontend/AGENTS.md, Hand-written types and the wire.",
    );
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `api-types-mirror: ${schemas.size} schema name(s) watched, ` +
        `${baseline.length - fixed.length} copy/copies still standing ` +
        `(all in the baseline).`,
    );
    if (fixed.length > 0) {
      console.log(
        `  ${fixed.length} baseline entr(y/ies) already converted — run ` +
          `--write-baseline to drop them.`,
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
