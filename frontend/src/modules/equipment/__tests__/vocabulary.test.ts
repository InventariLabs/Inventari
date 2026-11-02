import { describe, it, expect } from "vitest";
import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";
import map from "../vocabulary.json";

/**
 * The module's naming decision, as a measure.
 *
 * The equipment module names three different sets, and for a while it named
 * them with four interchangeable nouns (pl: zasoby/sprzęt/rekordy/urządzenia)
 * on one screen. The decision — which word names which set, and where the
 * zasób/rekord boundary runs — lives in prose in docs/MODULE_NAMES.md, in the
 * glossary of contested terms, entry "asset vs equipment vs record". What a
 * test can honestly enforce is not a
 * heuristic over name stems across the whole catalog (the earlier locations
 * unification measured that cross-family consistency is not structurally
 * checkable), but the curated map this module was asked for as the defensible premise
 * (vocabulary.json) plus these three narrow rules over it.
 */

const catalogs: Record<string, Record<string, unknown>> = {
  en,
  pl,
  de,
  fr,
  es,
};
const languages = Object.keys(catalogs);

const stems = map.stems as Record<
  string,
  {
    individual: string[];
    domain: string[];
    record: string[];
    forbiddenInIndividual: string[];
  }
>;
const featureNames = map.featureNames as Record<string, Record<string, string>>;

function flatten(
  obj: Record<string, unknown>,
  prefix = "",
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object") {
      Object.assign(out, flatten(v as Record<string, unknown>, full));
    } else if (typeof v === "string") {
      out[full] = v;
    }
  }
  return out;
}

const value = (lang: string, key: string): string => {
  const v = flatten(catalogs[lang])[key];
  if (v === undefined) throw new Error(`${lang}.json has no key ${key}`);
  return v;
};

const has = (text: string, needles: string[]) =>
  needles.some((n) => text.toLowerCase().includes(n.toLowerCase()));

describe("equipment vocabulary (the naming decision, as a measure)", () => {
  it("every curated individual key names the thing with the module's individual word", () => {
    for (const [key, requiresWord] of Object.entries(map.individualKeys)) {
      for (const lang of languages) {
        const text = value(lang, key);
        const bad = stems[lang].forbiddenInIndividual.filter((n) =>
          has(text, [n]),
        );
        expect(
          bad,
          `${lang} ${key} uses a word that is not the module's individual word: ${bad.join(", ")}`,
        ).toEqual([]);
        if (requiresWord) {
          expect(
            has(text, stems[lang].individual),
            `${lang} ${key} must name the thing with one of: ${stems[lang].individual.join(", ")}`,
          ).toBe(true);
        }
      }
    }
  });

  it("a retired word for the tracked thing appears nowhere in the catalog", () => {
    const retired = map.retiredWords as Record<string, string[] | string>;
    for (const lang of languages) {
      const words = retired[lang];
      if (!Array.isArray(words)) continue;
      const text = JSON.stringify(catalogs[lang]).toLowerCase();
      for (const word of words) {
        const count = text.split(word.toLowerCase()).length - 1;
        expect(
          count,
          `${lang}.json still says "${word}" ${count}× — the module's word is ${stems[lang].individual.join(" / ")}`,
        ).toBe(0);
      }
    }
  });

  it("keys that point at the My-Assets screen use that screen's real name in this language", () => {
    for (const [key, feature] of Object.entries(map.featureNameKeys)) {
      for (const lang of languages) {
        expect(
          value(lang, key).includes(featureNames[feature][lang]),
          `${lang} ${key} must reference the screen as "${featureNames[feature][lang]}"`,
        ).toBe(true);
      }
    }
  });

  it("a location's contents are counted in the cross-module word, never the module's own", () => {
    const exempt = new Set(Object.keys(map.recordExempt));
    for (const prefix of map.recordKeyPrefixes) {
      for (const lang of languages) {
        const flat = flatten(catalogs[lang]);
        const keys = Object.keys(flat).filter(
          (k) => k.startsWith(prefix) && !exempt.has(k),
        );
        expect(
          keys.length,
          `${lang} has no keys under ${prefix}`,
        ).toBeGreaterThan(0);
        for (const key of keys) {
          const text = flat[key];
          expect(
            has(text, stems[lang].record),
            `${lang} ${key} counts location contents and must use: ${stems[lang].record.join(", ")}`,
          ).toBe(true);
          expect(
            has(text, [...stems[lang].individual, ...stems[lang].domain]),
            `${lang} ${key} must not name location contents with the module's own words`,
          ).toBe(false);
        }
      }
    }
  });
});
