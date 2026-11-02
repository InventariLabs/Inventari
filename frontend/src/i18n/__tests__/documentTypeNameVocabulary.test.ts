/**
 * Helps speak in type names; paperwork codes are the user's data, not ours.
 *
 * The document settings and scan helps used to illustrate numbers with
 * paperwork codes — "PZ/2026/001" in four languages that never adopted them,
 * plus a private dialect per language (GRN, WE/WA/UML, ALB, RE/LI/TR). An
 * administrator reading English was asked to recognize Polish warehouse
 * shorthand, and every language carried a different invention.
 *
 * Neither a paperwork code nor a translated type name may stand in a number:
 * what a number looks like is the organization's numbering format, so the
 * scan help takes its example from the profile when it renders and the raw
 * string carries only the placeholder. A catalogue help may not carry any
 * all-caps token beyond the formatting placeholders it explains in words
 * beside the field.
 */
import { describe, expect, it } from "vitest";

import documentsEn from "@/modules/warehouse/i18n/en.json";
import documentsPl from "@/modules/warehouse/i18n/pl.json";
import documentsDe from "@/modules/warehouse/i18n/de.json";
import documentsFr from "@/modules/warehouse/i18n/fr.json";
import documentsEs from "@/modules/warehouse/i18n/es.json";

import recipesEn from "@/modules/recipes/i18n/en.json";
import recipesPl from "@/modules/recipes/i18n/pl.json";
import recipesDe from "@/modules/recipes/i18n/de.json";
import recipesFr from "@/modules/recipes/i18n/fr.json";
import recipesEs from "@/modules/recipes/i18n/es.json";

interface Catalogue {
  profile: Record<string, string>;
  scan: Record<string, string>;
}

const CATALOGUES: Record<string, Catalogue> = {
  en: documentsEn as unknown as Catalogue,
  pl: documentsPl as unknown as Catalogue,
  de: documentsDe as unknown as Catalogue,
  fr: documentsFr as unknown as Catalogue,
  es: documentsEs as unknown as Catalogue,
};

// Languages whose typesShort carries bare names: a help in these languages
// has no business carrying any all-caps token beyond the formatting
// placeholders the hint itself explains.
const NAME_BEARING_LANGUAGES = ["en", "de", "fr", "es"];

const ALLOWED_CAPS_TOKENS = new Set([
  // the tokens of the numbering format itself — every one of them is
  // explained in words beside the field
  "TYPE",
  "LABEL",
  "SEQ",
  "YEAR",
  "MONTH",
]);

// The placeholders the numbering engine substitutes. The help beside the
// field names each one: a manager editing the format reads what every part
// writes before typing it, instead of meeting a bare Python-style string.
const PLACEHOLDERS = [
  "{TYPE}",
  "{TYPE_LABEL}",
  "{YEAR}",
  "{MONTH}",
  "{SEQ:03d}",
];

const capsTokens = (value: string): string[] =>
  value.match(/\b[A-Z]{2,6}\b/g)?.filter((t) => !ALLOWED_CAPS_TOKENS.has(t)) ??
  [];

/**
 * The recipes settings help ("register production as … document") sat outside
 * the documents catalogue above and kept the paperwork code every other help
 * had already dropped — the fourth place a profile shortcut leaked into a
 * help. Unlike the numbering hints, these two keys have no
 * formatting placeholders to excuse a code, and the type has a name in every
 * language ("internal issue", "rozchód wewnętrzny"), so all five languages
 * are held to it — Polish included.
 */
const recipesSettings = (catalogue: unknown): Record<string, string> =>
  (catalogue as { settings: Record<string, string> }).settings;

const RECIPES_CATALOGUES: Record<string, unknown> = {
  en: recipesEn,
  pl: recipesPl,
  de: recipesDe,
  fr: recipesFr,
  es: recipesEs,
};

const PAPERWORK_CODES = /\b(PZ|WZ|MM|PW|RW|KOR)\b/;

describe("recipes production help names the document type", () => {
  for (const [lang, catalogue] of Object.entries(RECIPES_CATALOGUES)) {
    const settings = recipesSettings(catalogue);

    it(`carries no paperwork code (${lang})`, () => {
      for (const key of [
        "registerProductionAsDocument",
        "registerProductionAsDocumentDescription",
      ]) {
        expect(settings[key]).toBeDefined();
        expect(settings[key]).not.toMatch(PAPERWORK_CODES);
      }
    });
  }
});

describe("document helps illustrate numbers with the organisation's own numbering", () => {
  for (const [lang, cat] of Object.entries(CATALOGUES)) {
    it(`numberingFormatHint fills its example from the profile (${lang})`, () => {
      // The example is written into the string when it renders, from the
      // format, padding and receipt label the draft carries — so the hint
      // never promises a number the profile does not write (a language's
      // word where the engine writes the short code, "/001" beside a
      // four-digit sequence, no month for a monthly format). The raw string
      // carries the placeholder and no number of its own; the number it
      // writes is pinned where it renders, in DocumentFormatSettings.
      expect(cat.profile.numberingFormatHint).toContain("{{example}}");
      expect(cat.profile.numberingFormatHint).not.toMatch(/\d{4}\//);
    });

    it(`the format hint names every placeholder (${lang})`, () => {
      for (const token of PLACEHOLDERS) {
        expect(cat.profile.numberingFormatHint).toContain(token);
      }
    });

    it(`the scan help takes its example from the profile (${lang})`, () => {
      // What a number looks like is the organization's numbering format, not
      // a word of the language: the example is written into the string when
      // it renders — the format, labels and padding the profile carries — so
      // the hint can no longer promise a number no profile here ever wrote
      // ("Receipt/2026/0001", "PZ/2026/0001"). The raw string carries the
      // placeholder and no number of its own; the number it writes is pinned
      // where it renders, on the scan page.
      expect(cat.scan.numberHint).toContain("{{example}}");
      expect(cat.scan.numberHint).not.toMatch(/\d{4}\//);
    });

    if (NAME_BEARING_LANGUAGES.includes(lang)) {
      const helps = [
        cat.profile.numberingFormatHint,
        cat.profile.numberPaddingSharedHint,
        cat.scan.numberHint,
      ];

      it(`carries no paperwork code in its helps (${lang})`, () => {
        const strays = helps.flatMap(capsTokens);
        expect(strays).toEqual([]);
      });
    }
  }
});
