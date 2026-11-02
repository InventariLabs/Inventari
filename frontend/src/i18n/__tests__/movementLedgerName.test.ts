/**
 * One ledger, one name — the refusal and the footnote agree, per language.
 *
 * The backend composes its refusal as a translated sentence (the screen
 * prints `detail` verbatim where the table would be), and the screen writes
 * its own footnote about the same boundary from the report's `complete_from`
 * field. Two dictionaries that do not know each other named the entity
 * twice on one screen — "Księga ruchów" above "Rejestr ruchów" in Polish,
 * "registre" over "journal" in French, "registro" over "libro" in Spanish —
 * and dated it two ways, ISO in the sentence and the reader's format in the
 * footnote.
 *
 * Neither suite can check this alone: the backend container has no frontend
 * tree, and the frontend cannot compose the backend's sentence. So the check
 * reads both raw sources — the error catalogues and `LANGUAGE_DATE_FORMATS`
 * on one side, the footnote catalogues on the other — the same way
 * `scanServerKeys.test.ts` reads backend construction sites. The repo root
 * resolves the same on the host and in the frontend container, where the
 * backend tree is a sibling of `/app`.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import inventoryDe from "@/modules/inventory/i18n/de.json";
import inventoryEn from "@/modules/inventory/i18n/en.json";
import inventoryEs from "@/modules/inventory/i18n/es.json";
import inventoryFr from "@/modules/inventory/i18n/fr.json";
import inventoryPl from "@/modules/inventory/i18n/pl.json";

type Language = "en" | "pl" | "de" | "fr" | "es";

/** The screen's own sentence about the ledger's first day, per language. */
const FOOTNOTES: Record<Language, string> = {
  en: inventoryEn.asOf.completeFrom,
  pl: inventoryPl.asOf.completeFrom,
  de: inventoryDe.asOf.completeFrom,
  fr: inventoryFr.asOf.completeFrom,
  es: inventoryEs.asOf.completeFrom,
};

// Four directories up is the repo root — `frontend/src/i18n/__tests__` on
// the host, `/app/src/i18n/__tests__` in the container, where the backend
// tree sits next to `/app`. Three would land inside the frontend tree.
const REPO_ROOT = resolve(__dirname, "../../../../");

/** Which file holds each language's error catalogue (en and pl share one). */
const CATALOG_FILES: Record<Language, string> = {
  en: "backend/app/i18n/_errors_en_pl.py",
  pl: "backend/app/i18n/_errors_en_pl.py",
  de: "backend/app/i18n/_errors_de.py",
  fr: "backend/app/i18n/_errors_fr.py",
  es: "backend/app/i18n/_errors_es.py",
};

function readCatalog(lang: Language): string {
  return readFileSync(resolve(REPO_ROOT, CATALOG_FILES[lang]), "utf8");
}

/**
 * The refusal sentence for a language, out of the catalogue's source.
 *
 * The entry is one implicitly-concatenated single-quoted string, so the
 * segments are joined; `null` means the key moved or changed shape — which
 * is itself a finding, not a reason to pass vacuously.
 */
export function refusalSentence(
  catalogSource: string,
  lang: Language,
): string | null {
  const matches = [
    ...catalogSource.matchAll(/'stock_as_of_before_ledger':\s*\(([^)]*)\)/g),
  ];
  // The en_pl file carries both dictionaries, English first.
  const entry = lang === "pl" ? matches.at(-1) : matches[0];
  if (!entry) return null;
  const segments = entry[1].match(/'([^']*)'/g);
  if (!segments) return null;
  return segments.map((segment) => segment.slice(1, -1)).join("");
}

/** The footnote up to its date placeholder — the words both layers share. */
function footnoteStem(footnote: string): string {
  return footnote.split("{{date}}")[0].trim();
}

/** Where the two sentences disagree on the entity they name. */
export function nameDivergences(
  footnote: string,
  sentence: string | null,
): string[] {
  const found: string[] = [];
  if (sentence === null) {
    found.push("the refusal entry was not found in the catalogue source");
    return found;
  }
  const stem = footnoteStem(footnote);
  if (!stem) {
    found.push("the footnote has no {{date}} placeholder to stem at");
  } else if (!sentence.startsWith(stem)) {
    found.push(
      `the refusal says "${sentence.slice(0, stem.length + 10)}…" where the footnote says "${stem}…"`,
    );
  }
  return found;
}

/**
 * Render a strftime pattern of `%d`, `%m`, `%Y` and literals — the subset
 * `LANGUAGE_DATE_FORMATS` uses — the way the backend would.
 */
function strftime(pattern: string, day: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return pattern
    .replace(/%d/g, pad(day.getDate()))
    .replace(/%m/g, pad(day.getMonth() + 1))
    .replace(/%Y/g, String(day.getFullYear()));
}

/** The backend's date patterns, read out of `app/core/datetimes.py`. */
export function backendDateFormats(
  datetimesSource: string,
): Partial<Record<Language, string>> {
  const formats: Partial<Record<Language, string>> = {};
  for (const match of datetimesSource.matchAll(
    /'(en|pl|de|fr|es)':\s*'([^']+)'/g,
  )) {
    formats[match[1] as Language] = match[2];
  }
  return formats;
}

// A day that disambiguates order and padding: the 6th of September.
const SAMPLE_DAY = new Date(2026, 8, 6);

describe("the ledger's boundary carries one name and one date shape", () => {
  for (const lang of Object.keys(FOOTNOTES) as Language[]) {
    it(`names and dates it the way the screen does (${lang})`, () => {
      expect(
        nameDivergences(
          FOOTNOTES[lang],
          refusalSentence(readCatalog(lang), lang),
        ),
      ).toEqual([]);
    });
  }

  it("formats the day the way the screen's formatter does, per language", () => {
    // `formatDate` renders through Intl with 2-digit day and month and a
    // numeric year, resolved by the interface language — the claim
    // `LANGUAGE_DATE_FORMATS` makes in its comment, checked here for real.
    const source = readFileSync(
      resolve(REPO_ROOT, "backend/app/core/datetimes.py"),
      "utf8",
    );
    const formats = backendDateFormats(source);
    for (const lang of Object.keys(FOOTNOTES) as Language[]) {
      if (lang === "en") {
        // English spells the month out (`_english_date`), so it has no
        // numeric pattern: the screen's text is what the backend writes.
        expect(source).toContain("def _english_date");
        expect(
          new Intl.DateTimeFormat("en-US", {
            day: "numeric",
            month: "short",
            year: "numeric",
          }).format(SAMPLE_DAY),
        ).toBe("Sep 6, 2026");
        continue;
      }
      const pattern = formats[lang];
      expect(
        pattern,
        `${lang} has a date pattern in LANGUAGE_DATE_FORMATS`,
      ).toBeDefined();
      const screen = new Intl.DateTimeFormat(lang, {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      }).format(SAMPLE_DAY);
      expect(strftime(pattern as string, SAMPLE_DAY)).toBe(screen);
    }
  });

  it("would catch the refusal inventing its own name", () => {
    // The measured defect: the Polish refusal said "Księga ruchów…" two
    // rows above a footnote that said "Rejestr ruchów…".
    expect(
      nameDivergences(
        "Rejestr ruchów zaczyna się {{date}}.",
        "Księga ruchów zaczyna się 01.05.2026.",
      ),
    ).toContainEqual(
      'the refusal says "Księga ruchów zaczyna się 01.05.2026…" where the footnote says "Rejestr ruchów zaczyna się…"',
    );
  });

  it("would catch the entry disappearing from the catalogue", () => {
    expect(nameDivergences(FOOTNOTES.pl, null)).toEqual([
      "the refusal entry was not found in the catalogue source",
    ]);
  });

  it("would catch a date pattern drifting from the screen's order", () => {
    // ISO order in a Polish sentence was the other half of the same split.
    const screen = new Intl.DateTimeFormat("pl", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(SAMPLE_DAY);
    expect(strftime("%Y-%m-%d", SAMPLE_DAY)).not.toBe(screen);
  });
});
