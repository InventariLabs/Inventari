import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { type Language as Lang } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Module display-name parity guard (docs/MODULE_NAMES.md).
 *
 * The user-visible module name used to have four independent sources
 * (backend manifest, modules.json, launcher.title, README) that drifted
 * apart. This test enforces the repair rules mechanically:
 *
 * 1. Every backend-registered module (dir with manifest.json) plus the
 *    virtual `partners` module has `modules.<name>.name` and
 *    `modules.<name>.description` in ALL five modules.json catalogs, and no
 *    catalog carries a key that no module claims (the `statistics` vs `stats`
 *    typo class — five translations sat dead for months).
 * 2. A module whose frontend registration defines `launcher.displayName`
 *    must resolve that key to exactly the same string as
 *    `modules.<name>.name` in every language — the launcher tile, module
 *    switcher and command palette must not show a second name.
 * 3. The English visible name must not be the technical identifier
 *    (case-insensitive). Catches codenames like "Maker". A small allowlist
 *    holds reviewed exceptions whose English label legitimately equals the
 *    identifier ("Recipes", "Webhooks").
 *
 * The manifest `display_name` is deliberately NOT consulted: it is a
 * fallback for community modules, not an authority for first-party ones.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");
const REPO_ROOT = process.env.INVENTARI_REPO_ROOT ?? path.resolve(SRC, "../..");
const LOCALES = path.join(SRC, "i18n", "locales");
const FRONTEND_MODULES = path.join(SRC, "modules");
const BACKEND_MODULES = path.join(REPO_ROOT, "backend", "app", "modules");

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

const modulesCatalogs = Object.fromEntries(
  MAINTAINED_LANGUAGES.map((lang) => [
    lang,
    dig(
      readJson(path.join(LOCALES, lang, "modules.json")),
      "modules",
    ) as Catalog,
  ]),
) as Record<Lang, Catalog>;

/** Modules the backend registry can serve via GET /modules/available. */
const backendModules = fs
  .readdirSync(BACKEND_MODULES, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name)
  .filter((name) =>
    fs.existsSync(path.join(BACKEND_MODULES, name, "manifest.json")),
  )
  .sort();

/** Served by /modules/available without a backend module (app/api/modules.py). */
const VIRTUAL_MODULES = ["partners"] as const;
/** Always-on, rendered by the onboarding wizard from modules.core.title/desc. */
const CORE_KEY = "core";
/** Always-on features the org module list serves without a backend module
 *  (ALWAYS_ON_MODULES in app/core/module_safety.py, minus the names that are
 *  real module directories). They have no store card, but the settings screen
 *  still has to name them — by the card of the frontend module that renders
 *  the feature, never by the technical slug. */
const ALWAYS_ON_FEATURES = ["items"] as const;
/** The frontend module whose launcher tile carries the feature's card name. */
const FEATURE_CARD_MODULE: Record<(typeof ALWAYS_ON_FEATURES)[number], string> =
  { items: "inventory" };

const marketplaceModules = [...backendModules, ...VIRTUAL_MODULES];

/** Reads `launcher.displayName` from a frontend module.ts(x), null when absent/empty. */
function launcherDisplayNameKey(moduleName: string): string | null {
  for (const ext of ["ts", "tsx"] as const) {
    const file = path.join(FRONTEND_MODULES, moduleName, `module.${ext}`);
    if (!fs.existsSync(file)) continue;
    const match = fs
      .readFileSync(file, "utf8")
      .match(/displayName:\s*"([^"]+)"/);
    if (match) return match[1];
  }
  return null;
}

/**
 * Resolves an i18n reference like "maker:launcher.title" or bare
 * "navigation.shopping" (default `common` namespace) against the JSON
 * catalogs of one language — core locale file first, then module catalog.
 */
function resolveKey(reference: string, lang: Lang): string | undefined {
  const separator = reference.indexOf(":");
  const ns = separator >= 0 ? reference.slice(0, separator) : "common";
  const keyPath = separator >= 0 ? reference.slice(separator + 1) : reference;
  for (const file of [
    path.join(LOCALES, lang, `${ns}.json`),
    path.join(FRONTEND_MODULES, ns, "i18n", `${lang}.json`),
  ]) {
    if (!fs.existsSync(file)) continue;
    const value = dig(readJson(file), keyPath);
    if (typeof value === "string") return value;
  }
  return undefined;
}

describe("module name parity", () => {
  it("every marketplace module has name+description in all five locales", () => {
    const problems: string[] = [];
    for (const name of marketplaceModules) {
      for (const lang of MAINTAINED_LANGUAGES) {
        const entry = modulesCatalogs[lang][name];
        const moduleName = dig(entry, "name");
        const description = dig(entry, "description");
        if (typeof moduleName !== "string" || moduleName.trim() === "") {
          problems.push(`${lang}: modules.${name}.name missing or empty`);
        }
        if (typeof description !== "string" || description.trim() === "") {
          problems.push(
            `${lang}: modules.${name}.description missing or empty`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("the always-on core entry has title+desc in all five locales", () => {
    const problems: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      const entry = modulesCatalogs[lang][CORE_KEY];
      for (const field of ["title", "desc"] as const) {
        const value = dig(entry, field);
        if (typeof value !== "string" || value.trim() === "") {
          problems.push(
            `${lang}: modules.${CORE_KEY}.${field} missing or empty`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("no modules.json entry is orphaned (key must map to a known module)", () => {
    const known = new Set([
      ...marketplaceModules,
      CORE_KEY,
      ...ALWAYS_ON_FEATURES,
    ]);
    const problems: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      for (const key of Object.keys(modulesCatalogs[lang])) {
        if (!known.has(key)) {
          problems.push(
            `${lang}: modules.${key} has no module behind it (typo or stale rename)`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("launcher.displayName resolves to modules.<name>.name in every language", () => {
    const problems: string[] = [];
    for (const name of marketplaceModules) {
      const key = launcherDisplayNameKey(name);
      if (!key) continue;
      for (const lang of MAINTAINED_LANGUAGES) {
        const resolved = resolveKey(key, lang);
        const canonical = dig(modulesCatalogs[lang], `${name}.name`);
        if (resolved !== canonical) {
          problems.push(
            `${name} ${lang}: ${key} = ${JSON.stringify(resolved)}, expected ${JSON.stringify(canonical)}`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("an always-on feature is named by the card of the module that renders it", () => {
    // `items` and the inventory launcher tile are one product area with two
    // identifiers; the visible name may live on only one of them (rule 3
    // applied across the boundary).
    const problems: string[] = [];
    for (const feature of ALWAYS_ON_FEATURES) {
      const cardModule = FEATURE_CARD_MODULE[feature];
      for (const lang of MAINTAINED_LANGUAGES) {
        const name = dig(modulesCatalogs[lang], `${feature}.name`);
        const cardTitle = resolveKey(`${cardModule}:launcher.title`, lang);
        if (typeof name !== "string" || name.trim() === "") {
          problems.push(`${lang}: modules.${feature}.name missing or empty`);
          continue;
        }
        if (name !== cardTitle) {
          problems.push(
            `${feature} ${lang}: modules.${feature}.name = ${JSON.stringify(name)}, but the ${cardModule} card says ${JSON.stringify(cardTitle)}`,
          );
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("the English visible name is not the bare technical identifier", () => {
    // Reviewed exceptions whose English label legitimately equals the
    // identifier: loanwords used across all languages, the agreed Approvals
    // label, and Warehouse, whose key was renamed after its label
    // (docs/MODULE_NAMES.md).
    const allowlist = new Set([
      "recipes",
      "webhooks",
      "approvals",
      "warehouse",
    ]);
    const problems: string[] = [];
    for (const name of backendModules) {
      const enName = dig(modulesCatalogs.en, `${name}.name`);
      if (typeof enName !== "string") continue; // invariant 1 reports it
      if (enName.toLowerCase() === name.toLowerCase() && !allowlist.has(name)) {
        problems.push(
          `${name}: English name ${JSON.stringify(enName)} is the technical identifier — give it a real label in MODULE_NAMES.md`,
        );
      }
    }
    expect(problems).toEqual([]);
  });

  it("README names every product module by its agreed English name (rule 5)", () => {
    // example_widgets is a developer reference, not a product module — it is
    // deliberately absent from the public README.
    const readme = fs.readFileSync(path.join(REPO_ROOT, "README.md"), "utf8");
    const problems: string[] = [];
    for (const name of marketplaceModules) {
      if (name === "example_widgets") continue;
      const enName = dig(modulesCatalogs.en, `${name}.name`);
      if (typeof enName !== "string") continue; // invariant 1 reports it
      if (!readme.includes(`**${enName}**`)) {
        problems.push(`${name}: README does not mention **${enName}**`);
      }
    }
    expect(problems).toEqual([]);
  });

  it("the name table of MODULE_NAMES.md is the catalogs, row by row", () => {
    // The document is the decision record and the catalogs carry it out, so
    // the two have to say the same thing. Nothing compared them, and nine
    // description cells had drifted from the English catalog unnoticed. Each
    // row names the module in the five maintained languages, exactly as its
    // catalog does (`core` by its title), and its description opens with the
    // English catalog's; the row may add a note after it.
    const doc = fs.readFileSync(
      path.join(REPO_ROOT, "docs", "MODULE_NAMES.md"),
      "utf8",
    );
    const start = doc.indexOf("## Name table");
    const table = doc.slice(start, doc.indexOf("\n### ", start));
    const header = table
      .split("\n")
      .find((line) => line.startsWith("| Technical name"));
    const columns = (header ?? "").split("|").map((cell) => cell.trim());
    const rows = table
      .split("\n")
      .filter((line) => line.startsWith("| `"))
      .map((line) => line.split("|").map((cell) => cell.trim()));
    const documented = rows.map((cells) => /`([^`]+)`/.exec(cells[1])?.[1]);
    const problems: string[] = [];
    for (const cells of rows) {
      const name = /`([^`]+)`/.exec(cells[1])?.[1] ?? "";
      const nameKey = name === CORE_KEY ? "title" : "name";
      for (const lang of MAINTAINED_LANGUAGES) {
        const expected = dig(modulesCatalogs[lang], `${name}.${nameKey}`);
        const cell = cells[columns.indexOf(lang)];
        if (cell !== expected) {
          problems.push(
            `${name} [${lang}]: table ${JSON.stringify(cell)}, catalog ${JSON.stringify(expected)}`,
          );
        }
      }
      const descriptionKey = name === CORE_KEY ? "desc" : "description";
      const description = dig(modulesCatalogs.en, `${name}.${descriptionKey}`);
      const cell = cells[columns.indexOf("One-sentence description")];
      if (typeof description === "string" && !cell.startsWith(description)) {
        problems.push(
          `${name}: description ${JSON.stringify(cell)} does not open with ${JSON.stringify(description)}`,
        );
      }
    }
    expect(problems).toEqual([]);
    expect(new Set(documented)).toEqual(
      new Set(Object.keys(modulesCatalogs.en)),
    );
  });
});
