import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import en from "@/modules/maker/i18n/en.json";
import pl from "@/modules/maker/i18n/pl.json";
import de from "@/modules/maker/i18n/de.json";
import fr from "@/modules/maker/i18n/fr.json";
import es from "@/modules/maker/i18n/es.json";

/**
 * glossary in docs/MODULE_NAMES.md: the maker module's production
 * input has exactly one term per language, and it is never the culinary word.
 *
 * - en: **BOM** (expanded in launcher.description as "bills of materials
 *   (BOM)"). "Formula" and "production recipe" are banned — they collided
 *   with the recipes module and forced rescue adjectives like "culinary".
 * - pl: receptura, de: Formel, fr: formule, es: fórmula — each internally
 *   consistent, none borrowing the recipes module's word.
 *
 * Sole exception everywhere: `detail.sourceRecipe`, which points back at the
 * culinary recipe the BOM was created from — that reference keeps the kitchen
 * word on purpose, without the rescue adjective.
 *
 * The glossary is one, the catalogs are two: a refusal from the maker API is
 * worded in the backend's error catalog (backend/app/i18n/_errors_*.py) and
 * lands in the same sentence on the same screen as this module's labels. So
 * every rule below reads both — the maker's own JSON catalogs and every
 * server message whose key the maker module raises.
 */

const CATALOGS = { en, pl, de, fr, es } as const;

type Leaf = [path: string, value: string];

function leaves(node: unknown, prefix = ""): Leaf[] {
  if (typeof node === "string") return [[prefix, node]];
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) =>
      leaves(v, prefix ? `${prefix}.${k}` : k),
    );
  }
  return [];
}

/** Every string in the catalog except the deliberate culinary back-reference. */
function copyWithoutSourceRecipe(catalog: typeof en): Leaf[] {
  return leaves(catalog).filter(([p]) => p !== "detail.sourceRecipe");
}

type Lang = keyof typeof CATALOGS;

/** `<src>/../..` — the repo root on the host, `/` in the frontend container (read-only mount). */
const BACKEND_APP = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../../backend/app",
);

/** One Python string literal, either quote style; group 1 or 2 is its body. */
const PY_STRING = /'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g;

function unescapePy(body: string): string {
  return body.replace(/\\(.)/g, (_m, ch: string) => (ch === "n" ? "\n" : ch));
}

/**
 * key → message per language, read from the catalog modules themselves.
 * `_errors_en_pl.py` nests two languages under `'en': {` / `'pl': {`; the
 * others hold one each, named by the file. A message may span lines as
 * implicitly concatenated literals inside parentheses.
 */
function serverCatalogs(): Record<Lang, Map<string, string>> {
  const out = Object.fromEntries(
    Object.keys(CATALOGS).map((lang) => [lang, new Map<string, string>()]),
  ) as Record<Lang, Map<string, string>>;
  const dir = join(BACKEND_APP, "i18n");
  for (const file of readdirSync(dir).filter((f) =>
    /^_errors_.*\.py$/.test(f),
  )) {
    let lang = file.match(/^_errors_([a-z]{2})\.py$/)?.[1] as Lang | undefined;
    let key: string | undefined;
    for (const line of readFileSync(join(dir, file), "utf8").split("\n")) {
      const section = line.match(/^ {4}'([a-z]{2})': \{$/);
      if (section) {
        lang = section[1] as Lang;
        key = undefined;
        continue;
      }
      if (/^\s*#/.test(line)) continue;
      const entry = line.match(/^\s+'([a-z0-9_]+)':(.*)$/);
      const rest = entry ? entry[2] : line;
      if (entry) key = entry[1];
      // A community language's catalog is not held to the maker's vocabulary.
      if (!lang || !key || !(lang in out)) continue;
      const parts = [...rest.matchAll(PY_STRING)].map((m) =>
        unescapePy(m[1] ?? m[2]),
      );
      if (parts.length === 0) continue;
      const catalog = out[lang];
      catalog.set(key, (catalog.get(key) ?? "") + parts.join(""));
    }
  }
  return out;
}

/** The maker module's backend source, tests excluded, as one text. */
function makerSource(): string {
  const root = join(BACKEND_APP, "modules/maker");
  return readdirSync(root, { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".py") && !f.split("/").includes("tests"))
    .map((f) => readFileSync(join(root, f), "utf8"))
    .join("\n");
}

const SERVER = serverCatalogs();
const MAKER_SOURCE = makerSource();
/**
 * The server messages that are the maker's: their key is quoted somewhere in
 * maker code. Searched key by key rather than by pairing every quote in the
 * source — an apostrophe in a comment would shift the pairs and hide keys.
 */
const MAKER_SERVER_KEYS = [...SERVER.en.keys()].filter((k) =>
  new RegExp(`['"]${k}['"]`).test(MAKER_SOURCE),
);

/** The maker's copy in one language: its own catalog plus its server messages. */
function makerCopy(lang: Lang): Leaf[] {
  return [
    ...copyWithoutSourceRecipe(CATALOGS[lang]),
    ...MAKER_SERVER_KEYS.map((k): Leaf => [
      `server:${k}`,
      SERVER[lang].get(k) ?? "",
    ]),
  ];
}

describe("the server half of the maker's copy", () => {
  // an empty extraction would pass every rule below — the instrument has to
  // fail loudly when the catalogs outgrow the parser
  it("finds the maker's keys in the server catalog", () => {
    expect(MAKER_SERVER_KEYS).toContain("bom_line_not_found");
    expect(MAKER_SERVER_KEYS).toContain("production_no_recipe");
    expect(MAKER_SERVER_KEYS).not.toContain("recipe_not_found");
  });

  it("reads multi-line messages whole", () => {
    expect(SERVER.en.get("bom_depth_exceeded")).toBe(
      "This BOM is nested more than {max_depth} levels deep — too deep to resolve.",
    );
  });

  it.each(Object.keys(CATALOGS))("has every maker message in %s", (lang) => {
    const missing = MAKER_SERVER_KEYS.filter(
      (k) => !SERVER[lang as Lang].get(k),
    );
    expect(missing).toEqual([]);
  });
});

describe("maker BOM terminology", () => {
  it("en uses BOM everywhere and never formula/recipe", () => {
    const offenders = makerCopy("en").filter(([, v]) =>
      /\bformulas?\b|\brecipes?\b/i.test(v),
    );
    expect(offenders).toEqual([]);
  });

  it("en expands the acronym at the module's entry point", () => {
    expect(en.launcher.description).toMatch(/bills of materials \(BOM\)/i);
  });

  it("every language spells the acronym BOM, never mixed-case BoM", () => {
    const offenders = Object.keys(CATALOGS).flatMap((lang) =>
      makerCopy(lang as Lang)
        .filter(([, v]) => /BoM/.test(v))
        .map(([path, value]) => `${lang}:${path}: ${value}`),
    );
    expect(offenders).toEqual([]);
  });

  it.each([
    ["pl", /przepis/i],
    ["de", /rezept/i],
    ["fr", /recett/i],
    ["es", /recet/i],
  ] as const)(
    "%s never borrows the culinary word for the production input",
    (lang, culinaryWord) => {
      const offenders = makerCopy(lang).filter(([, v]) => culinaryWord.test(v));
      expect(offenders).toEqual([]);
    },
  );

  it.each(Object.entries(CATALOGS))(
    "%s keeps the recipes-module back-reference free of rescue adjectives",
    (_lang, catalog) => {
      expect(catalog.detail.sourceRecipe).not.toMatch(/culinar|kulinar/i);
    },
  );
});

/**
 * The field behind both labels is `yield_loss_pct` — a percentage that gets
 * *subtracted*. English called it "Yield %", which names the opposite
 * quantity: a reader enters 10 meaning "a tenth comes out" and the BOM drops
 * a tenth instead. The two call sites word it differently on purpose —
 * `bom.*` is a visible label with the form around it, `detail.line.*` is an
 * aria-label that has to stand alone — so the contract is not equal strings,
 * it is that both name a loss.
 */
const LOSS_WORD: Record<keyof typeof CATALOGS, RegExp> = {
  en: /loss/i,
  pl: /strat/i,
  de: /verlust/i,
  fr: /perte/i,
  es: /p[ée]rdida/i,
};

describe("maker yield-loss labels", () => {
  it.each(Object.entries(CATALOGS))(
    "%s names a loss at both call sites of yield_loss_pct",
    (lang, catalog) => {
      const word = LOSS_WORD[lang as keyof typeof CATALOGS];
      expect(catalog.bom.yieldLabel).toMatch(word);
      expect(catalog.detail.line.yieldLabel).toMatch(word);
    },
  );
});
