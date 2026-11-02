import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { type Language as Lang } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Workspace-mode name parity guard (docs/MODULE_NAMES.md § "Workspace mode
 * names").
 *
 * The sibling guard `moduleNameParity.test.ts` compared module names and not
 * profile names, which is exactly how "Clean Core" shipped untranslated to
 * three screens. This test enforces the same rules one storey up:
 *
 * 1. Every shipped profile has `profiles.<id>.name` and
 *    `profiles.<id>.description` in ALL five common.json catalogs.
 * 2. Outside `en`, neither text is byte-identical to the English one — the
 *    signature of a placeholder pasted across the five files.
 * 3. No component renders `profile.name` / `profile.description` directly;
 *    every label goes through `useProfileLabels`. A raw read is invisible to
 *    invariants 1 and 2 — the catalog can be perfect while the screen still
 *    shows the registry's English.
 * 4. The English label is not the profile id, and carries no architecture
 *    vocabulary ("core").
 *
 * The profile list is static: the frontend does not reach the backend in unit
 * tests. `test_fallback_labels_are_present_and_not_the_identifier` in
 * `backend/tests/unit/test_product_profiles.py` guards the other direction —
 * a profile added to the registry without a label.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");
const LOCALES = path.join(SRC, "i18n", "locales");

/** Profiles shipped in `backend/app/core/product_profiles.py`. */
const PROFILE_IDS = ["food_home", "equipment_wms", "clean_core"] as const;

type Catalog = Record<string, unknown>;

function readJson(file: string): Catalog {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Catalog;
}

function dig(node: unknown, dotted: string): unknown {
  let cur: unknown = node;
  for (const key of dotted.split(".")) {
    if (cur == null || typeof cur !== "object" || Array.isArray(cur))
      return undefined;
    cur = (cur as Catalog)[key];
  }
  return cur;
}

const catalogs = Object.fromEntries(
  MAINTAINED_LANGUAGES.map((lang) => [
    lang,
    (dig(readJson(path.join(LOCALES, lang, "common.json")), "profiles") ??
      {}) as Catalog,
  ]),
) as Record<Lang, Catalog>;

/** Every .ts/.tsx under src/, minus the hook and the tests that assert on it. */
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (
      /\.tsx?$/.test(entry.name) &&
      !/\.test\.tsx?$/.test(entry.name)
    ) {
      out.push(full);
    }
  }
  return out;
}

describe("workspace mode name parity", () => {
  it("every shipped profile has name+description in all five locales", () => {
    const problems: string[] = [];
    for (const id of PROFILE_IDS) {
      for (const lang of MAINTAINED_LANGUAGES) {
        for (const field of ["name", "description"] as const) {
          const value = dig(catalogs[lang][id], field);
          if (typeof value !== "string" || value.trim() === "") {
            problems.push(`${lang}: profiles.${id}.${field} missing or empty`);
          }
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("no locale ships the English text as a placeholder", () => {
    const problems: string[] = [];
    for (const id of PROFILE_IDS) {
      for (const field of ["name", "description"] as const) {
        const english = dig(catalogs.en[id], field);
        if (typeof english !== "string") continue; // invariant 1 reports it
        for (const lang of MAINTAINED_LANGUAGES) {
          if (lang === "en") continue;
          if (dig(catalogs[lang][id], field) === english) {
            problems.push(
              `${lang}: profiles.${id}.${field} is still the English text`,
            );
          }
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("no catalog entry is orphaned (key must map to a shipped profile)", () => {
    const known = new Set<string>(PROFILE_IDS);
    const problems: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      for (const key of Object.keys(catalogs[lang])) {
        if (!known.has(key)) {
          problems.push(
            `${lang}: profiles.${key} has no profile behind it (typo or stale rename)`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("no component renders a profile label without the hook", () => {
    const hook = path.join(
      SRC,
      "modules",
      "settings",
      "hooks",
      "useProfileLabels.ts",
    );
    // `profile.name`, `profile?.description`, `selectedProfile.name`, … but
    // not `profileLabels(profile).name`, which reads through the resolver.
    const rawRead = /\b\w*[Pp]rofile\??\.(name|description)\b/;
    const problems: string[] = [];
    for (const file of sourceFiles(SRC)) {
      if (file === hook) continue;
      const source = fs.readFileSync(file, "utf8");
      source.split("\n").forEach((line, index) => {
        if (rawRead.test(line)) {
          problems.push(
            `${path.relative(SRC, file)}:${index + 1}: ${line.trim()} — ` +
              `use useProfileLabels instead of the registry field`,
          );
        }
      });
    }
    expect(problems).toEqual([]);
  });

  it("the audit log names the workspace mode with the same word as its field label", () => {
    // One audit row prints the target type and the changed field side by
    // side; two words for one concept in a row is the defect this guards.
    const problems: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      const common = readJson(path.join(LOCALES, lang, "common.json"));
      const field = dig(common, "settings.audit.fields.profile_id");
      const target = dig(common, "settings.audit.targetTypes.product_profile");
      if (field !== target) {
        problems.push(
          `${lang}: targetTypes.product_profile ${JSON.stringify(target)} ` +
            `differs from fields.profile_id ${JSON.stringify(field)}`,
        );
      }
    }
    expect(problems).toEqual([]);
  });

  it("the English label is neither the identifier nor an architecture word", () => {
    const problems: string[] = [];
    for (const id of PROFILE_IDS) {
      const name = dig(catalogs.en[id], "name");
      if (typeof name !== "string") continue; // invariant 1 reports it
      if (name.toLowerCase() === id.toLowerCase()) {
        problems.push(`${id}: English name is the profile id`);
      }
      if (/\bcore\b/i.test(name)) {
        problems.push(
          `${id}: English name ${JSON.stringify(name)} uses "Core" — an ` +
            `architecture word, not a user concept`,
        );
      }
    }
    expect(problems).toEqual([]);
  });
});
