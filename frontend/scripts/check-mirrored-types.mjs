#!/usr/bin/env node
/**
 * check-mirrored-types.mjs
 *
 * A hand-written type that claims to mirror the wire is checked against it.
 *
 * 186 non-test files import types from `@/types`; twelve import the
 * generated ones. The hand-written layer is not going away tomorrow, and
 * while it exists nothing compares it with what the backend actually sends —
 * so `tsc` is green over a declaration that is wrong. It has been wrong in
 * both directions that matter: `DocumentLine.quantity` typed `number` where
 * the wire sends a Decimal as text, which turned an addition into string
 * concatenation; and `Category.category_type` narrowed to three food values
 * where the backend types a plain string, so every comparison against a
 * category from another vertical answered "no" without a word.
 *
 * An interface opts in with `@mirrors components["schemas"]["X"]` in its
 * doc comment. This then compares, field by field: presence, optionality and
 * the primitive type where both sides state one. It is not a type checker —
 * it is the question nobody was asking.
 *
 * The path out is `types/inventory.ts`'s own precedent: replace the
 * interface with an alias to the generated schema. A mirror is the stop on
 * the way, not the destination; see docs in frontend/AGENTS.md.
 *
 * Modes:
 *   node check-mirrored-types.mjs           # report and exit 1 on findings
 *   node check-mirrored-types.mjs --quiet   # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const GENERATED = resolve(SRC, "types/api-generated.ts");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/** `{ interfaceName: schemaName }` for every interface that opted in. */
export function mirrorDeclarations(text) {
  const found = {};
  const pattern =
    /@mirrors\s+components\[\s*"schemas"\s*\]\[\s*"([^"]+)"\s*\][\s\S]{0,400}?export interface (\w+)/g;
  for (const match of text.matchAll(pattern)) {
    found[match[2]] = match[1];
  }
  return found;
}

/** Field name -> `{ optional, type }` for one interface or schema body. */
export function fieldsOf(body) {
  const fields = {};
  let depth = 0;
  for (const raw of body.split("\n")) {
    const line = raw.trim();
    if (depth === 0) {
      const match = line.match(/^(\w+)(\??):\s*(.+?);?$/);
      if (match && !line.startsWith("//") && !line.startsWith("*")) {
        fields[match[1]] = {
          optional: match[2] === "?",
          type: match[3].replace(/;$/, "").trim(),
        };
      }
    }
    depth += (line.match(/\{/g) || []).length;
    depth -= (line.match(/\}/g) || []).length;
    if (depth < 0) depth = 0;
  }
  return fields;
}

function bodyOf(text, header) {
  const start = text.indexOf(header);
  if (start < 0) return null;
  let depth = 0;
  for (let i = text.indexOf("{", start); i < text.length; i += 1) {
    if (text[i] === "{") depth += 1;
    if (text[i] === "}") {
      depth -= 1;
      if (depth === 0) return text.slice(text.indexOf("{", start) + 1, i);
    }
  }
  return null;
}

/** Types that describe the same wire value in different words. */
const EQUIVALENT = [
  ["Record<string, unknown> | null", "{ [key: string]: unknown } | null"],
  ["Record<string, unknown>", "{ [key: string]: unknown }"],
];

function sameType(manual, generated) {
  const normalise = (t) => t.replace(/\s+/g, " ").trim();
  const a = normalise(manual);
  const b = normalise(generated);
  if (a === b) return true;
  return EQUIVALENT.some(
    ([x, y]) => (a === x && b === y) || (a === y && b === x),
  );
}

export function compare(name, manualFields, generatedFields) {
  const problems = [];
  for (const [field, manual] of Object.entries(manualFields)) {
    const generated = generatedFields[field];
    if (!generated) {
      problems.push(`${name}.${field}: not on the wire at all`);
      continue;
    }
    if (manual.optional !== generated.optional) {
      problems.push(
        `${name}.${field}: ${manual.optional ? "optional" : "required"} here, ` +
          `${generated.optional ? "optional" : "required"} on the wire`,
      );
    }
    if (
      !manual.type.includes("{") &&
      !generated.type.includes("{") &&
      !sameType(manual.type, generated.type)
    ) {
      problems.push(
        `${name}.${field}: ${manual.type} here, ${generated.type} on the wire`,
      );
    }
  }
  for (const field of Object.keys(generatedFields)) {
    if (!(field in manualFields)) {
      problems.push(`${name}.${field}: on the wire, missing here`);
    }
  }
  return problems;
}

function main() {
  const generatedSource = readFileSync(GENERATED, "utf8");
  const problems = [];
  let mirrors = 0;

  for (const file of walk(SRC)) {
    const rel = relative(ROOT, file).replaceAll("\\", "/");
    if (!rel.endsWith(".ts") || rel.endsWith("api-generated.ts")) continue;
    const text = readFileSync(file, "utf8");
    for (const [interfaceName, schemaName] of Object.entries(
      mirrorDeclarations(text),
    )) {
      mirrors += 1;
      const manualBody = bodyOf(text, `export interface ${interfaceName}`);
      // Eight spaces: the schema level of the generated file. Without
      // the indent, "Category" matched "ByCategory" — a stats row with
      // two fields — and the check reported every field as missing.
      const generatedBody = bodyOf(
        generatedSource,
        `\n        ${schemaName}: {`,
      );
      if (!generatedBody) {
        problems.push(
          `${rel}: ${interfaceName} mirrors ${schemaName}, which the ` +
            "generated schema does not contain",
        );
        continue;
      }
      problems.push(
        ...compare(
          interfaceName,
          fieldsOf(manualBody),
          fieldsOf(generatedBody),
        ).map((p) => `${rel}: ${p}`),
      );
    }
  }

  if (problems.length > 0) {
    console.error(
      `\nmirrored-types: ${problems.length} difference(s) between a ` +
        "hand-written type and the wire it claims to mirror:\n",
    );
    for (const problem of problems) console.error(`  ${problem}`);
    console.error(
      "\nFix the declaration, or replace it with an alias to " +
        'components["schemas"][...] — see frontend/AGENTS.md.',
    );
    process.exit(1);
  }

  if (!process.argv.includes("--quiet")) {
    console.log(
      `mirrored-types: ${mirrors} mirrored interface(s) agree with the wire.`,
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
