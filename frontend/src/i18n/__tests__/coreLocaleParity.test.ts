import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { SUPPORTED_LANGUAGES, isCommunityLanguage } from "../languages";
import {
  type CoverageDeclaration,
  coverageFindings,
  coverageOf,
  enKeySet,
  listLanguages,
  readCoverageDeclaration,
} from "../../test/localeCatalog";

/**
 * The core translation gate: the locales directory is the set of shipped
 * languages, and every language is held to a coverage number it declared.
 *
 * It used to import twenty locale files by hand and hold a five-language
 * constant. A directory added per the new-language recipe was invisible to
 * it — the gate stayed green while measuring nothing for that language,
 * which is worse than red: it looked like a measurement and was not. The
 * directory is now read as data, and the gate holds it to the application's
 * own list in both directions: an orphan directory fails, a listed language
 * without a directory fails.
 *
 * Two classes of language, declared in `languages.ts`. A maintained language
 * (pl, de, fr, es) is complete by rule: every English key, always, and its
 * declaration must say 100. A community language gets partial credit, per
 * the dead-code gates' baseline pattern (knip, check:i18n:unused, vulture):
 * it declares its coverage in `frontend/scripts/translation-coverage.json`,
 * and the gate fails only when the actual coverage drops below the declared
 * number — never on the mere fact of being unfinished. Its test title names
 * its number, so a reader can see they are looking at a translation whose
 * missing keys fall back to English (i18next fallbackLng). en is the source
 * and is never listed. Refresh the declarations only by writing what is:
 * TRANSLATION_COVERAGE_WRITE=1 (mirrors CONSOLE_BASELINE_WRITE), never by
 * hand.
 *
 * The gate watches the four core namespaces it has always watched
 * (common, items, labels, storages); module catalogs carry their own parity
 * tests next to the module.
 */

const LOCALES = resolve(__dirname, "../locales");
const COVERAGE_FILE = resolve(
  __dirname,
  "../../../scripts/translation-coverage.json",
);
const CORE_NAMESPACES = ["common", "items", "labels", "locations"];

/** A key ending in a plural suffix is a form of an existing key, not a
 *  sentence of its own — languages with more plural categories than English
 *  legitimately carry extras (Polish _few/_many, and every future language
 *  of the same shape). */
const PLURAL_EXTRA = /_(one|few|many|other)$/;

const languages = listLanguages(LOCALES);
const enKeys = enKeySet(LOCALES, CORE_NAMESPACES);

if (process.env.TRANSLATION_COVERAGE_WRITE) {
  const written: CoverageDeclaration = {};
  for (const language of languages) {
    if (language === "en") continue;
    const coverage = coverageOf(LOCALES, language, CORE_NAMESPACES, enKeys);
    written[language] = isCommunityLanguage(language)
      ? { percent: coverage.percent, keys: coverage.present }
      : coverage.percent;
  }
  writeFileSync(COVERAGE_FILE, `${JSON.stringify(written, null, 2)}\n`);
  process.stdout.write(
    `translation coverage written: ${COVERAGE_FILE} ${JSON.stringify(written)}\n`,
  );
}

const declaration = readCoverageDeclaration(COVERAGE_FILE);

describe("the locale directory and the shipped language list agree", () => {
  it("every language directory is shipped, and every shipped language has a directory", () => {
    expect(languages).toEqual([...SUPPORTED_LANGUAGES].sort());
  });
});

describe("declared translation coverage", () => {
  it("has a coverage file to hold languages to", () => {
    // Without it there is no baseline — the gate would be asked to pretend
    // a measurement happened. Create it with the write mode, never by hand.
    expect(declaration).not.toBeNull();
  });

  it("declares every shipped language except en, in the shape of its class", () => {
    const undeclared = languages.filter((language) => {
      if (language === "en") return false;
      const entry = declaration?.[language];
      return isCommunityLanguage(language)
        ? typeof entry !== "object" || entry === null
        : typeof entry !== "number";
    });
    expect(undeclared).toEqual([]);
  });

  for (const language of languages) {
    if (language === "en") continue;
    const declared = declaration?.[language];
    if (declared === undefined) continue;

    const coverage = coverageOf(LOCALES, language, CORE_NAMESPACES, enKeys);

    if (typeof declared === "object") {
      it(`${language}: a community translation — keeps the ${declared.keys} keys it declared, missing ones fall back to en`, () => {
        // Held to the keys it declared, not to a share of English: a change
        // adds strings to the maintained languages and leaves this one to
        // catch up in a batch.
        expect(
          coverageFindings(coverage, {
            community: true,
            declaredKeys: declared.keys,
          }),
        ).toEqual([]);
      });
    } else {
      it(`${language}: maintained, holds every en key`, () => {
        // Whatever the declaration says: a maintained language is never
        // excused a gap by a baseline.
        expect(
          coverageFindings(coverage, { community: false, declaredKeys: 0 }),
        ).toEqual([]);
      });

      it(`${language}: a maintained language is declared complete`, () => {
        expect(declared).toBe(100);
      });
    }

    it(`${language}: no keys beyond en's, except plural forms`, () => {
      const illegitimate = coverage.extra.filter(
        (key) => !PLURAL_EXTRA.test(key),
      );
      expect(illegitimate).toEqual([]);
    });
  }
});
