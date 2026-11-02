import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

import { listLanguages, readCoverageDeclaration } from "../test/localeCatalog";
import { isCommunityLanguage } from "./languages";

/**
 * Every catalog key the label scan can send, resolved in every language the
 * locales directory carries.
 *
 * The server cannot know the language of the person holding the phone, so it
 * answers with a key and the client resolves it (`message_key` on
 * `LabelScanResponse`). Nothing on the server side can check that key —
 * a container running the backend suite has no catalogues to read, and the
 * static i18n gate cannot see a key that arrives over the wire at runtime.
 * So the check lives here, on the side that owns the catalogues, and it
 * reads the keys out of the construction sites themselves rather than from
 * a list somebody has to remember to extend — and the languages out of the
 * same directory, so a language added per the recipe is scanned without any
 * list in this file being edited.
 *
 * A key the catalogue does not hold is not an error the reader can decode:
 * i18next prints the key, so the phone shows "scan:result.labelReady" under
 * a status that says "NIEPRZYPISANA". A language declared as a translation
 * in progress (a community language, declared in languages.ts) may miss a
 * key — i18next falls back to English per key, so the phone still shows a
 * sentence, never a raw key — and this test then requires only that English
 * holds the key. A maintained language is held to the full set.
 */

const BACKEND_APP = resolve(__dirname, "../../../backend/app");
const LOCALES = resolve(__dirname, "locales");
// One directory up from src/i18n is frontend/, then scripts/. Not three:
// with three this resolved to <repo>/scripts, the declaration read null, and
// the tolerance below silently stopped existing while complete catalogs kept
// the gate green. The guard at the bottom of this file holds that down.
const COVERAGE_FILE = resolve(
  __dirname,
  "../../scripts/translation-coverage.json",
);

const LANGUAGES = listLanguages(LOCALES);
const COVERAGE = readCoverageDeclaration(COVERAGE_FILE);

/** A community language falls back to English per key; a maintained one is
 *  held to the full set. */
function mayFallBackToEn(language: string): boolean {
  return language !== "en" && isCommunityLanguage(language);
}

function pythonFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "tests" || entry === "__pycache__") continue;
      pythonFiles(path, out);
    } else if (entry.endsWith(".py")) {
      out.push(path);
    }
  }
  return out;
}

/** The literal keys handed to `message_key=` across the backend. */
function scanMessageKeys(): { key: string; file: string }[] {
  const found: { key: string; file: string }[] = [];
  for (const path of pythonFiles(BACKEND_APP)) {
    const source = readFileSync(path, "utf-8");
    if (
      !source.includes("LabelScanResponse") &&
      !source.includes("LabelScanDTO")
    )
      continue;
    for (const match of source.matchAll(/message_key='([^']+)'/g)) {
      found.push({
        key: match[1],
        file: path.slice(path.indexOf("backend/app/") + 11),
      });
    }
  }
  return found;
}

function resolveKey(key: string, language: string): string | null {
  const [namespace, path] = key.split(":");
  const catalog = join(LOCALES, language, `${namespace}.json`);
  if (!existsSync(catalog)) return null;
  let node: unknown = JSON.parse(readFileSync(catalog, "utf-8"));
  for (const segment of path.split(".")) {
    if (typeof node !== "object" || node === null) return null;
    node = (node as Record<string, unknown>)[segment];
  }
  // A blank value is no more a sentence than a missing key is — a phone
  // showing nothing under "NIEPRZYPISANA" is the same silence. en itself
  // is held to this: no catalog is above the rule.
  return typeof node === "string" && node.trim() !== "" ? node : null;
}

describe("the label scan's keys", () => {
  it("are handed over as keys, one per branch of the scan chain", () => {
    const keys = scanMessageKeys();
    // Nine construction sites in the core provider — the answer that names
    // a shelf is built in one place for the three providers that find one —
    // plus one in each module that ships a provider of its own (nutrition,
    // warehouse). The count is
    // here so a branch added without a key — or a provider that stops
    // handing one over — is a failure rather than a quietly shorter list.
    expect(keys).toHaveLength(11);
    expect(new Set(keys.map((k) => k.key)).size).toBeGreaterThanOrEqual(7);
  });

  it("resolve in every language the application ships", () => {
    const unresolved: string[] = [];
    for (const { key, file } of scanMessageKeys()) {
      for (const language of LANGUAGES) {
        if (resolveKey(key, language) !== null) continue;
        // A translation in progress misses keys by declaration; the phone
        // must still see a sentence, so en has to hold the key.
        if (mayFallBackToEn(language) && resolveKey(key, "en") !== null) {
          continue;
        }
        unresolved.push(`${language} ${key} (${file})`);
      }
    }
    expect(unresolved).toEqual([]);
  });
});

describe("the declaration this file tolerates partial languages by", () => {
  // The test above depends on the coverage file to exist and to name every
  // language in the directory. With the declaration missing, the fallback
  // silently never applies: green on today's complete catalogs, wrongly red
  // the day a partial language lands. This is where that failure is loud.
  it("is readable and declares every language but en", () => {
    expect(COVERAGE).not.toBeNull();
    const undeclared = LANGUAGES.filter(
      (language) => language !== "en" && COVERAGE?.[language] === undefined,
    );
    expect(undeclared).toEqual([]);
  });
});
