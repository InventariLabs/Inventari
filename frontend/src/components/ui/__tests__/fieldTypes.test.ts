import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { OPTIONS_REQUIRED_TYPES } from "../fieldTypes";

/**
 * The builder offers the reader a list of field types. The API refuses
 * anything outside its own list. When the two drift, the form is one a
 * reader can fill in and not submit — which is how a `uom_select` that
 * exists in no backend and no screen sat in the shared type for months.
 *
 * Read out of the Python rather than restated here: a copy of the list in
 * this file would be the fifth copy, and the drift would move into it.
 */
const SCHEMA_RELATIVE = "backend/app/schemas/category.py";

/** Walk up until the repository root — the frontend is mounted at different
 * depths in the container and in CI. */
function findSchema(): string {
  let dir = __dirname;
  for (let i = 0; i < 10; i += 1) {
    const candidate = resolve(dir, SCHEMA_RELATIVE);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`${SCHEMA_RELATIVE} not found above ${__dirname}`);
}

const SCHEMA = findSchema();

function backendLiteral(source: string, name: string): string[] {
  const block = new RegExp(
    `${name}[^=]*=\\s*(?:Literal|frozenset\\()?\\[?\\{?([^\\]}]*)`,
  ).exec(source);
  if (!block) throw new Error(`${name} not found in ${SCHEMA}`);
  return [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
}

describe("the field types the builder offers", () => {
  const source = readFileSync(SCHEMA, "utf8");

  it("are the ones the API accepts", () => {
    const backend = backendLiteral(source, "FieldType");
    // The union is a type, so it is checked through the labels the builder
    // renders: `TYPE_LABELS` in FieldBuilder.tsx has one entry per type.
    const builder = readFileSync(
      resolve(__dirname, "../FieldBuilder.tsx"),
      "utf8",
    );
    const labelBlock =
      /const TYPE_LABELS: Record<FieldType, string> = \{([\s\S]*?)\n {2}\};/.exec(
        builder,
      );
    expect(labelBlock).not.toBeNull();
    const offered = [...labelBlock![1].matchAll(/^\s*"?([\w-]+)"?:/gm)].map(
      (m) => m[1],
    );

    expect([...offered].sort()).toEqual([...backend].sort());
  });

  it("agree on which of them need an options list", () => {
    const backend = backendLiteral(source, "_OPTIONS_REQUIRED_TYPES");
    expect([...OPTIONS_REQUIRED_TYPES].sort()).toEqual([...backend].sort());
  });
});
