import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * One thing, one name.
 *
 * A periodic asset check went by three names, sometimes on one screen: the
 * navigation and the heading said "Attestations", the button said "New
 * Campaign", the modal said "New Audit Campaign". A second, unread copy of
 * the navigation block had drifted further still — pl called it
 * "Inwentaryzacje" (stocktakes) and de/fr/es called it an audit campaign.
 *
 * The route and the API keep saying `campaigns`. Those are identifiers;
 * nobody reads them. This guard is about the words on the screen.
 */
const CATALOGS = { en, pl, de, fr, es } as Record<
  string,
  Record<string, unknown>
>;

/** How each language spells the word we settled on. */
const ATTESTATION = {
  en: /attestation/i,
  pl: /atestacj/i,
  de: /attestierung/i,
  fr: /attestation/i,
  es: /atestaci/i,
};

/** How each language spells the campaign status the API returns. */
const ACTIVE = {
  en: /^active$/i,
  pl: /^aktywna$/i,
  de: /^aktiv$/i,
  fr: /^active$/i,
  es: /^activa$/i,
};

/** What it must no longer be called. */
const FORBIDDEN = {
  en: /campaign|audit/i,
  pl: /kampani|inwentaryzacj/i,
  de: /kampagne/i,
  fr: /campagne/i,
  es: /campañ/i,
};

function leaves(node: unknown, prefix: string[] = []): Array<[string, string]> {
  if (typeof node === "string") return [[prefix.join("."), node]];
  if (node && typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
      leaves(v, [...prefix, k]),
    );
  }
  return [];
}

describe("the attestation has one name in every language", () => {
  it.each(Object.keys(CATALOGS))("%s says nothing about campaigns", (lang) => {
    const forbidden = FORBIDDEN[lang as keyof typeof FORBIDDEN];
    const offenders = leaves(CATALOGS[lang]).filter(([, value]) =>
      forbidden.test(value),
    );

    expect(offenders).toEqual([]);
  });

  it.each(Object.keys(CATALOGS))(
    "%s names the campaign status the way the API does",
    (lang) => {
      // The badge used to read "Running" while the API said ACTIVE — an
      // export and the screen disagreed about the same row.
      const active = ACTIVE[lang as keyof typeof ACTIVE];
      const status = (
        CATALOGS[lang] as {
          attestation: { status: Record<string, string> };
        }
      ).attestation.status;

      expect(active.test(status.ACTIVE)).toBe(true);
    },
  );

  it.each(Object.keys(CATALOGS))("%s calls it an attestation", (lang) => {
    const word = ATTESTATION[lang as keyof typeof ATTESTATION];
    const catalog = CATALOGS[lang] as { attestation: Record<string, unknown> };

    expect(word.test(String(catalog.attestation.newCampaign))).toBe(true);
    expect(word.test(String(catalog.attestation.createTitle))).toBe(true);
    expect(word.test(String(catalog.attestation.create))).toBe(true);
  });

  it("names the holder's screen the way the navigation names it", () => {
    // The checkout hint promised the asset would appear under "My equipment",
    // a screen the navigation calls "My Assets".
    for (const [lang, catalog] of Object.entries(CATALOGS)) {
      const nav = (catalog.nav as Record<string, string>).my_assets;
      const hint = (
        (catalog.assignments as Record<string, Record<string, string>>)
          .checkout_modal as Record<string, string>
      ).email_consequence;
      expect(hint, `${lang} hint should name ${nav}`).toContain(nav);
    }
  });
});
