import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { type Language as Lang } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Entry copy for the modules a newcomer confuses (docs/MODULE_NAMES.md).
 *
 * Recipes vs Production and Shopping lists vs Purchase orders answer the
 * same question — "where is my jam recipe?", "which one buys?" — and their
 * names alone do not say which. The tile blurb and the page subtitle are
 * the two places that can: each names who the module is for and the job it
 * does.
 *
 * This guard holds the surfaces, not the wording (wording is checked by
 * eye and by the terminology guards): both strings resolve in every
 * language, the page subtitle is its own sentence rather than the module
 * blurb again, each module's list page carries the subtitle through its
 * nav item, and a sound-alike pair does not end up with one shared blurb.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");
const FRONTEND_MODULES = path.join(SRC, "modules");
const LOCALES = path.join(SRC, "i18n", "locales");

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

/**
 * Resolves an i18n reference like "maker:launcher.description" against one
 * language's catalogs — the module catalog first, like the launcher does.
 */
function resolveKey(reference: string, lang: Lang): string | undefined {
  const separator = reference.indexOf(":");
  const ns = separator >= 0 ? reference.slice(0, separator) : "common";
  const keyPath = separator >= 0 ? reference.slice(separator + 1) : reference;
  for (const file of [
    path.join(FRONTEND_MODULES, ns, "i18n", `${lang}.json`),
    path.join(LOCALES, lang, `${ns}.json`),
  ]) {
    if (!fs.existsSync(file)) continue;
    const value = dig(readJson(file), keyPath);
    if (typeof value === "string") return value;
  }
  return undefined;
}

/** The tile blurb and the list page's subtitle for one confusable module. */
const ENTRY_COPY = [
  {
    module: "recipes",
    landingPath: "/recipes",
    blurb: "recipes:launcher.description",
    pageSubtitle: "recipes:page.subtitle",
  },
  {
    module: "maker",
    landingPath: "/maker",
    blurb: "maker:launcher.description",
    pageSubtitle: "maker:catalog.subtitle",
  },
  {
    module: "shopping_lists",
    landingPath: "/shopping-lists",
    blurb: "shopping_lists:launcher.description",
    pageSubtitle: "shopping_lists:subtitle",
  },
  {
    module: "purchase_orders",
    landingPath: "/purchase-orders",
    blurb: "purchase_orders:launcher.description",
    pageSubtitle: "purchase_orders:subtitle",
  },
] as const;

/** The pairs that sound alike: one question, two different answers. */
const SOUND_ALIKE = [
  { a: "recipes", b: "maker" },
  { a: "shopping_lists", b: "purchase_orders" },
] as const;

function blurbOf(module: string): string {
  const entry = ENTRY_COPY.find((e) => e.module === module);
  if (!entry) throw new Error(`no entry copy recorded for ${module}`);
  return entry.blurb;
}

/** The nav item block in a module.ts, from its `path:` to the next item. */
function navItemBlock(module: string, itemPath: string): string {
  const source = fs.readFileSync(
    path.join(FRONTEND_MODULES, module, "module.ts"),
    "utf8",
  );
  const start = source.indexOf(`path: "${itemPath}"`);
  expect(start, `${module} has a nav item for ${itemPath}`).toBeGreaterThan(-1);
  const rest = source.slice(start);
  const next = rest.indexOf("path:", 10);
  return next < 0 ? rest : rest.slice(0, next);
}

describe("module entry copy", () => {
  it.each(ENTRY_COPY)(
    "$module names on the tile and on the page who it is for and what it does",
    ({ blurb, pageSubtitle }) => {
      for (const lang of MAINTAINED_LANGUAGES) {
        const tile = resolveKey(blurb, lang);
        const page = resolveKey(pageSubtitle, lang);
        expect(tile?.trim(), `${lang}: ${blurb}`).toBeTruthy();
        expect(page?.trim(), `${lang}: ${pageSubtitle}`).toBeTruthy();
        // A screen subtitle that repeats the tile adds nothing — the tile
        // blurb is the sentence the reader has just clicked through.
        expect(page, `${lang}: ${pageSubtitle}`).not.toBe(tile);
      }
    },
  );

  it.each(ENTRY_COPY)(
    "$module list page carries its subtitle through the nav item",
    ({ module, landingPath, pageSubtitle }) => {
      expect(navItemBlock(module, landingPath)).toContain(
        `subtitleKey: "${pageSubtitle}"`,
      );
    },
  );

  it.each(SOUND_ALIKE)(
    "$a tells itself apart from $b on the tile",
    ({ a, b }) => {
      for (const lang of MAINTAINED_LANGUAGES) {
        expect(
          resolveKey(blurbOf(a), lang),
          `${lang}: ${a} and ${b} share one blurb`,
        ).not.toBe(resolveKey(blurbOf(b), lang));
      }
    },
  );
});

/**
 * The tile clamps its blurb to two lines, which at desktop width show about
 * fifty characters, so what the release note promises about the Warehouse
 * module has to be said before the cut, not after it.
 */
const WAREHOUSE_PHONE_CAMERA = {
  en: "phone's camera",
  de: "Handykamera",
  es: "cámara del teléfono",
  fr: "caméra du téléphone",
  pl: "aparatem telefonu",
  pt: "câmera do celular",
} as const;
const TILE_VISIBLE_CHARACTERS = 50;

describe("warehouse tile blurb", () => {
  it("names the phone's camera inside the two lines the tile shows", () => {
    for (const lang of MAINTAINED_LANGUAGES) {
      const blurb = (
        resolveKey("warehouse:launcher.description", lang) ?? ""
      ).toLowerCase();
      const term = WAREHOUSE_PHONE_CAMERA[lang].toLowerCase();
      const end = blurb.indexOf(term) + term.length;
      expect(end, `${lang}: ${term} is in the blurb`).toBeGreaterThan(0);
      expect(end, `${lang}: ${term} ends before the clamp`).toBeLessThanOrEqual(
        TILE_VISIBLE_CHARACTERS,
      );
    }
  });
});
