import declaredCoverage from "../../scripts/translation-coverage.json";

/**
 * The one list of the languages the application ships.
 *
 * It used to live inside `config.ts`, and every other place that needed the
 * set copied it: the language picker, two test gates and the whole backend
 * each carried their own five codes (see the new-language recipe in
 * CONTRIBUTING.md). The gates now read the locales directory instead of a
 * list in code; this module stays the runtime's own answer — what the
 * detector may resolve, what the picker offers, what the API accepts — and
 * the parity gate holds the directory and this list to each other.
 *
 * One entry per language, carrying the picker's display metadata alongside
 * the code: `Language`, `SUPPORTED_LANGUAGES`, `LANGUAGE_NAMES` and the
 * picker's menu are all this array, so there is no second list a sixth
 * language can be added to and forgotten.
 */
export const LANGUAGES = [
  { code: "en", name: "EN", fullName: "English", flag: "🇬🇧" },
  { code: "pl", name: "PL", fullName: "Polski", flag: "🇵🇱" },
  { code: "de", name: "DE", fullName: "Deutsch", flag: "🇩🇪" },
  { code: "fr", name: "FR", fullName: "Français", flag: "🇫🇷" },
  { code: "es", name: "ES", fullName: "Español", flag: "🇪🇸" },
  {
    code: "pt",
    name: "PT",
    fullName: "Português (Brasil)",
    flag: "🇧🇷",
    community: true,
  },
] as const satisfies readonly {
  code: string;
  name: string;
  fullName: string;
  flag: string;
  /** Ships below full coverage: no change has to translate it, and a key it
   *  has not got yet is read in English. Every other language is maintained —
   *  a change brings all of them and the gates require the full set. */
  community?: true;
}[];

export type Language = (typeof LANGUAGES)[number]["code"];

export const SUPPORTED_LANGUAGES: Language[] = LANGUAGES.map(
  (language) => language.code,
);

/** The language's own name. A reader addressed by a code is being talked to
 *  in codes; every language arrives here with its name, instead of surfacing
 *  as raw code wherever a name was copied by hand. */
type LanguageEntry = (typeof LANGUAGES)[number];

/** Whether the language is a community translation (see `LANGUAGES`). */
export function isCommunityLanguage(language: string): boolean {
  return LANGUAGES.some(
    (entry: LanguageEntry) =>
      entry.code === language && "community" in entry && entry.community,
  );
}

/**
 * How much of the English interface a community language has, in percent —
 * the number the menu shows next to its name.
 *
 * It is the number the coverage gate holds the language to
 * (`frontend/scripts/translation-coverage.json`), so the menu cannot promise
 * more than the gate guards. A maintained language is complete by rule and
 * has no number to show.
 */
export function communityCoverage(language: Language): number | null {
  if (!isCommunityLanguage(language)) return null;
  const declared = (
    declaredCoverage as Record<string, number | { percent: number }>
  )[language];
  return typeof declared === "object" ? Math.floor(declared.percent) : null;
}

export const LANGUAGE_NAMES: Record<Language, string> = Object.fromEntries(
  LANGUAGES.map((language) => [language.code, language.fullName]),
) as Record<Language, string>;

/**
 * The language the reader asked for, narrowed to one this application ships.
 *
 * A bare code wins; a regional tag (`en-GB`) falls back to its base
 * language; anything else falls back to English. Lives here rather than in
 * `config.ts` so the test mock of that module can call the real thing
 * instead of keeping a second copy of this decision.
 */
export function resolveLang(raw: string | undefined): Language {
  if (!raw) return "en";
  if (SUPPORTED_LANGUAGES.includes(raw as Language)) return raw as Language;
  const prefix = raw.split("-")[0];
  const match = SUPPORTED_LANGUAGES.find((l) => prefix === l);
  return match ?? "en";
}
