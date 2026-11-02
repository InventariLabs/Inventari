import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * i18next interpolates `{{token}}` only. A single-brace `{token}` in a
 * catalogue string is never substituted — it renders literally, and the
 * reader sees "Only units convertible into {unit} are offered." with the
 * braces on screen. This walks every catalogue so the next single-brace
 * placeholder fails here instead of on a page.
 */

const SRC = resolve(__dirname, "..");

// Not i18next placeholders but the document-numbering pattern's own syntax —
// the string teaches the reader what to type into the pattern field.
const ALLOWLIST: ReadonlyArray<{ file: RegExp; key: string }> = [
  { file: /warehouse[\\/]i18n[\\/]/, key: "profile.numberingFormatHint" },
];

const SINGLE_BRACE = /(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})/;

function* walkStrings(
  value: unknown,
  path: string[] = [],
): Generator<{ keyPath: string; text: string }> {
  if (typeof value === "string") {
    yield { keyPath: path.join("."), text: value };
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      yield* walkStrings(child, [...path, key]);
    }
  }
}

function catalogueFiles(): string[] {
  const files: string[] = [];
  const localesDir = resolve(SRC, "i18n/locales");
  for (const lang of readdirSync(localesDir)) {
    for (const file of readdirSync(resolve(localesDir, lang))) {
      if (file.endsWith(".json")) files.push(resolve(localesDir, lang, file));
    }
  }
  for (const moduleDir of readdirSync(resolve(SRC, "modules"))) {
    const i18nDir = resolve(SRC, "modules", moduleDir, "i18n");
    let entries: string[];
    try {
      entries = readdirSync(i18nDir);
    } catch {
      continue;
    }
    for (const file of entries) {
      if (file.endsWith(".json")) files.push(resolve(i18nDir, file));
    }
  }
  return files;
}

describe("i18n catalogues — placeholders", () => {
  it("interpolation placeholders are double-braced everywhere", () => {
    const offenders: string[] = [];
    for (const file of catalogueFiles()) {
      const parsed: unknown = JSON.parse(readFileSync(file, "utf8"));
      for (const { keyPath, text } of walkStrings(parsed)) {
        if (!SINGLE_BRACE.test(text)) continue;
        const allowed = ALLOWLIST.some(
          ({ file: filePattern, key }) =>
            filePattern.test(file) && keyPath === key,
        );
        if (!allowed) {
          offenders.push(`${file} → ${keyPath}: ${text.slice(0, 80)}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

/**
 * The key paths an object in *text* names twice. `JSON.parse` keeps the last
 * of two equal keys without a word, so an edit to the first copy would be
 * silently ignored — the documents catalogues carried their whole `posted`
 * section twice in all five languages.
 */
function duplicateKeys(text: string): string[] {
  const found: string[] = [];
  // One frame per open object (its keys so far) or array (null).
  const stack: Array<{ keys: Set<string>; path: string } | null> = [];
  let expectKey = false;
  let lastKey = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      let end = i + 1;
      while (text[end] !== '"') end += text[end] === "\\" ? 2 : 1;
      const top = stack[stack.length - 1];
      if (top && expectKey) {
        const key = JSON.parse(text.slice(i, end + 1)) as string;
        const path = top.path ? `${top.path}.${key}` : key;
        if (top.keys.has(key)) found.push(path);
        top.keys.add(key);
        lastKey = path;
        expectKey = false;
      }
      i = end;
    } else if (ch === "{") {
      stack.push({ keys: new Set(), path: stack.length ? lastKey : "" });
      expectKey = true;
    } else if (ch === "[") {
      stack.push(null);
    } else if (ch === "}" || ch === "]") {
      stack.pop();
    } else if (ch === ",") {
      expectKey = stack[stack.length - 1] != null;
    }
  }
  return found;
}

describe("i18n catalogues — keys", () => {
  it("names no key twice in one object", () => {
    const offenders = catalogueFiles().flatMap((file) =>
      duplicateKeys(readFileSync(file, "utf8")).map((k) => `${file} → ${k}`),
    );
    expect(offenders).toEqual([]);
  });
});
