import { describe, expect, it } from "vitest";

/**
 * No catalogue names the same key twice in one object.
 *
 * `JSON.parse` keeps the last of two equal keys without a word, so an edit
 * to the first copy does nothing on screen while every other check — parity,
 * usage, plurals — reads the parsed object and stays green. The warehouse
 * catalogues carried their `posted` block twice this way.
 *
 * The files are read as text, because the parsed import has already lost
 * the duplicate.
 */

const rawCatalogues = import.meta.glob<string>(
  ["../locales/*/*.json", "../../modules/*/i18n/*.json"],
  { eager: true, query: "?raw", import: "default" },
);

/** The dotted paths of every key that appears twice in its own object. */
function duplicatedKeys(text: string): string[] {
  const found: string[] = [];
  const stack: { path: string; keys: Set<string> }[] = [];
  // Strings are walked whole so a brace or colon inside a value is not
  // read as structure; a string followed by a colon is a key.
  const token = /"((?:[^"\\]|\\.)*)"\s*(:)?|[{}[\]]/g;
  let match: RegExpExecArray | null;
  let pendingKey: string | null = null;
  while ((match = token.exec(text)) !== null) {
    const [whole, key, colon] = match;
    if (whole === "{") {
      const parent = stack[stack.length - 1];
      const path =
        parent && pendingKey !== null
          ? `${parent.path}${parent.path ? "." : ""}${pendingKey}`
          : "";
      stack.push({ path, keys: new Set() });
      pendingKey = null;
    } else if (whole === "}") {
      stack.pop();
    } else if (colon && key !== undefined) {
      const current = stack[stack.length - 1];
      if (current.keys.has(key)) {
        found.push(`${current.path}${current.path ? "." : ""}${key}`);
      }
      current.keys.add(key);
      pendingKey = key;
    }
  }
  return found;
}

describe("translation catalogues", () => {
  it("finds the catalogues", () => {
    expect(Object.keys(rawCatalogues).length).toBeGreaterThan(20);
  });

  it("reads a key named twice in one object", () => {
    expect(duplicatedKeys('{"a": {"b": "{x}", "b": "y"}, "c": "b"}')).toEqual([
      "a.b",
    ]);
  });

  it.each(Object.entries(rawCatalogues))(
    "%s names each key once per object",
    (_file, text) => {
      expect(duplicatedKeys(text)).toEqual([]);
    },
  );
});
