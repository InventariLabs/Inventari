/**
 * One concept, one word (UI_GUIDELINES §14.2).
 *
 * A place stock is kept is a Location, at every level of the tree. "Place",
 * "zone", "room" and "spot" are not synonyms to reach for — the screens used
 * to say Your Places / Storages / All locations / rooms at once, leaving no
 * way to tell whether those were four things or one. The Polish words
 * "lokalizacja" and "magazyn" are retired for it too: the word is "miejsce",
 * and "Magazyn" is the name of the warehouse module.
 *
 * This checks the **labels**: titles, headings, button captions, placeholders
 * — the strings that name a thing. Explanatory sentences are left to a
 * reader's judgement, because a language's ordinary word for "somewhere" is
 * not always a claim about the hierarchy ("move them there", in Polish, uses
 * the same noun the level used to be called by).
 *
 * Each language bans the synonyms of its own canonical pair. German's word
 * for a Location *is* "Ort", so German bans "Zone" and "Raum" instead —
 * which is the whole point: the offence is having two words for one level,
 * not any particular word.
 *
 * ADR-018 removed the declared levels, and with them the last reason to have
 * a word for one: "site", "zone" and "building" named a rung on a ladder that
 * no longer exists, so they join the list.
 *
 * Internal identifiers may lag behind (the wizard's suggestion catalogue is
 * still keyed `zones`); user-visible strings may not.
 */
import { describe, expect, it } from "vitest";

import storagesEn from "@/i18n/locales/en/locations.json";
import storagesPl from "@/i18n/locales/pl/locations.json";
import storagesDe from "@/i18n/locales/de/locations.json";
import storagesFr from "@/i18n/locales/fr/locations.json";
import storagesEs from "@/i18n/locales/es/locations.json";
import stockTakesEn from "@/modules/stock_takes/i18n/en.json";

const BANNED: Record<string, RegExp> = {
  en: /\b(places?|zones?|rooms?|spots?|sites?|buildings?)\b/i,
  pl: /\b(lokalizacj\w*|magazyn(?:y|ów|ach|ami|u|ie)?|stref\w*|pokoj\w*|budynk\w*|budynek)\b/i,
  de: /\b(Zonen?|R[äa]ume?n?|Geb[äa]uden?)\b/i,
  fr: /\b(zones?|lieux?|sites?|b[âa]timents?)\b/i,
  es: /\b(zonas?|lugar\w*|sitios?|edificios?)\b/i,
};

/** Keys whose value names something, as opposed to explaining it. */
const LABEL_KEY = /(title|subtitle|label|placeholder|name|heading|add\w*)$/i;

/**
 * Names people type in, not words the interface chooses: the sample
 * hierarchies the wizard offers are content, and "Zone A" is a perfectly good
 * name for a bay if that is what somebody calls it.
 */
const CONTENT_KEYS = [/^suggestions\./, /^wizard\.suggestions\./];

function visibleStrings(
  node: unknown,
  path = "",
): Array<{ path: string; value: string }> {
  if (typeof node === "string") return [{ path, value: node }];
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => visibleStrings(v, `${path}[${i}]`));
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) =>
      visibleStrings(v, path ? `${path}.${k}` : k),
    );
  }
  return [];
}

export function offenders(catalogue: unknown, pattern: RegExp) {
  return visibleStrings(catalogue)
    .filter(({ path }) => !CONTENT_KEYS.some((re) => re.test(path)))
    .filter(({ path }) => LABEL_KEY.test(path.split(".").pop() ?? ""))
    .filter(({ value }) => pattern.test(value));
}

describe("the location vocabulary is one word for every level", () => {
  it.each([
    ["en", storagesEn, BANNED.en],
    ["pl", storagesPl, BANNED.pl],
    ["de", storagesDe, BANNED.de],
    ["fr", storagesFr, BANNED.fr],
    ["es", storagesEs, BANNED.es],
  ])("names no second word for a level in %s", (_lang, catalogue, pattern) => {
    expect(offenders(catalogue, pattern)).toEqual([]);
  });

  it("holds for the stock-take screens that pick a storage", () => {
    expect(offenders(stockTakesEn, BANNED.en)).toEqual([]);
  });

  it("would catch a synonym coming back", () => {
    expect(
      offenders({ form: { storageLabel: "Pick a zone" } }, BANNED.en),
    ).toEqual([{ path: "form.storageLabel", value: "Pick a zone" }]);
  });

  it("would catch a level name coming back", () => {
    // The three fixed levels were Site, Zone and Location. Two of them are
    // gone from the model; a screen that names one is describing a ladder
    // the tree does not have.
    expect(offenders({ addSite: "Add site" }, BANNED.en)).toEqual([
      { path: "addSite", value: "Add site" },
    ]);
  });
});
