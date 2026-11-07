/**
 * Polish copy that speaks to the reader must not guess their gender.
 *
 * "Złożyłeś", "Zapomniałeś", "Już zrobiłem" are right for half of the
 * readers and wrong for the rest; a passive or an impersonal phrasing is
 * right for all of them. The check reads the values of every Polish
 * catalogue for a past-tense first or second person form.
 *
 * The launcher line about the organization is checked too: the default
 * Polish organization name already says "Organizacja", so a sentence that
 * names the noun again reads "Utworzono organizację Organizacja: Piotr".
 */
import { describe, expect, it } from "vitest";

import plLauncher from "../../modules/launcher/i18n/pl.json";

const catalogues = import.meta.glob<Record<string, unknown>>(
  ["../locales/pl/*.json", "../../modules/*/i18n/pl.json"],
  { eager: true, import: "default" },
);

const LETTER = "a-ząćęłńóśźż";
// A verb stem before the ending: "hasłem" (a password, instrumental) is not
// a past tense, "zrobiłem" and "zapisałeś" are.
const GENDERED_PAST = new RegExp(
  `[${LETTER}]+[iyaą]ł(em|am|eś|aś)(?![${LETTER}])`,
  "i",
);

function* strings(value: unknown, path: string): Generator<[string, string]> {
  if (typeof value === "string") yield [path, value];
  else if (Array.isArray(value))
    for (const [i, v] of value.entries()) yield* strings(v, `${path}[${i}]`);
  else if (value && typeof value === "object")
    for (const [k, v] of Object.entries(value))
      yield* strings(v, path ? `${path}.${k}` : k);
}

describe("Polish catalogues", () => {
  it("use no gendered past-tense form to address the reader", () => {
    const found: string[] = [];
    for (const [file, catalogue] of Object.entries(catalogues)) {
      for (const [path, text] of strings(catalogue, "")) {
        if (GENDERED_PAST.test(text)) found.push(`${file} ${path}: ${text}`);
      }
    }
    expect(found).toEqual([]);
  });

  it("do not repeat the word organization around the default organization name", () => {
    expect(plLauncher.launcher.createdOrganization).not.toMatch(/organizacj/i);
    expect(plLauncher.launcher.joinedOrganization).not.toMatch(/organizacj/i);
  });
});
