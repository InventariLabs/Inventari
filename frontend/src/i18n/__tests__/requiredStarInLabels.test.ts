/**
 * The required-field star is drawn, not written.
 *
 * `RequiredStar` (components/ui/fieldLabel) renders it inside the label and
 * hides it from the accessibility tree, so a screen reader says the field
 * name and "required" instead of "star". A star baked into the translation
 * defeats both halves — and travels wherever the string does: "Category Name
 * *" was the placeholder inside the category preview swatch, because the
 * preview reads the same key the label does.
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs from the frontend root; `import.meta.url` carries a `/@fs/`
// prefix here, which no path helper resolves back to a real directory.
const SRC = join(process.cwd(), "src");

function catalogues(): string[] {
  const found: string[] = [];
  const locales = resolve(SRC, "i18n/locales");
  for (const lang of readdirSync(locales)) {
    for (const file of readdirSync(resolve(locales, lang))) {
      if (file.endsWith(".json")) found.push(resolve(locales, lang, file));
    }
  }
  const modules = resolve(SRC, "modules");
  for (const mod of readdirSync(modules)) {
    const dir = resolve(modules, mod, "i18n");
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir)) {
      if (file.endsWith(".json")) found.push(resolve(dir, file));
    }
  }
  return found;
}

/** Leaf strings ending in a bare star — " *", "*", " \*" and friends. */
export function starredStrings(
  node: unknown,
  path = "",
): Array<{ path: string; value: string }> {
  if (typeof node === "string") {
    return /\s\*\s*$/.test(node) ? [{ path, value: node }] : [];
  }
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => starredStrings(v, `${path}[${i}]`));
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) =>
      starredStrings(v, path ? `${path}.${k}` : k),
    );
  }
  return [];
}

describe("no translation writes the required star itself", () => {
  it("finds none in any catalogue", () => {
    const offenders = catalogues().flatMap((file) => {
      const relative = file.slice(SRC.length + 1);
      return starredStrings(JSON.parse(readFileSync(file, "utf8"))).map(
        ({ path, value }) => `${relative}: ${path} = ${JSON.stringify(value)}`,
      );
    });
    expect(offenders).toEqual([]);
  });

  it("would catch one coming back", () => {
    expect(starredStrings({ modal: { nameLabel: "Category Name *" } })).toEqual(
      [{ path: "modal.nameLabel", value: "Category Name *" }],
    );
  });

  it("leaves a star that is part of a word alone", () => {
    expect(starredStrings({ hint: "Use *bold* for emphasis" })).toEqual([]);
  });
});
