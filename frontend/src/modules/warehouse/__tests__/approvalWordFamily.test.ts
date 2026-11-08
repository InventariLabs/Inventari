import { describe, expect, it } from "vitest";

import de from "../i18n/de.json";
import pl from "../i18n/pl.json";

/**
 * One word family for approval, counted over the whole catalogue — the
 * rule is stated for Polish and German.
 *
 * German is "Genehmigung", the word the approvals module, the purchase
 * orders, the equipment module and the API's own messages already use; the
 * warehouse module said "Freigabe" for the same thing, so the configuration
 * tab and the workflow read "Freigabe ausstehend" beside a queue that read
 * "Genehmigungsanfragen" and "Genehmigt". Polish had already been walked key
 * by key onto "akceptacja". A walk over the touched keys is what let twelve
 * German values survive the first pass: verbs and the agent noun are family
 * too, not just the "-ung" noun.
 *
 * So this counts every string in the file, and allows the other family only
 * where the word is not about approval at all: German "freigeben" is also
 * "release" — a document released for execution, a scan session released
 * when idle — and the confirm verb in Polish, which the rule itself lets
 * stand beside "akceptacja". The approvals module's Polish name,
 * "Zatwierdzenia", is a name and not the word: where a string names the
 * module (or the settings section that is its), it says what the store and
 * the launcher say (docs/MODULE_NAMES.md, rule 1).
 */
const COMPETING: Record<string, RegExp> = {
  pl: /zatwierd/i,
  de: /freigab|freigeb|freigeg|freigib/i,
};

const PINNED: Record<string, string[]> = {
  // "Zatwierdź i wykonaj", "zatwierdź dokument", "Zatwierdź i zamknij" —
  // the confirm verb, which the rule allows to stand beside "akceptacja";
  // and the module's name.
  pl: ["Zatwierdź", "zatwierdź", "Zatwierdzenia"],
  // Releasing is not approving: the document goes to the floor, the idle
  // scan session lets go of its document.
  de: [
    "zur Lagerausführung freigegeben",
    "Scan-Sitzung freigeben",
    "Scan-Sitzung ihr Dokument freigibt",
  ],
};

const CATALOGUES: Record<string, unknown> = { pl, de };

/** Every use of the competing family in the file, after the pinned phrases
 * are taken out. Returned as matches so a failure names the word. */
export function competingWords(
  serialized: string,
  competing: RegExp,
  pinned: string[],
): string[] {
  let rest = serialized;
  for (const phrase of pinned) rest = rest.split(phrase).join("");
  // Forcing `g`: `String.match` without it returns one match carrying
  // `index` and `input`, which `toEqual` compares as well.
  const all = new RegExp(
    competing.source,
    `${competing.flags.replace("g", "")}g`,
  );
  return [...rest.matchAll(all)].map((match) => match[0]);
}

describe("the warehouse module names approval with one family per language", () => {
  for (const [language, catalog] of Object.entries(CATALOGUES)) {
    it(`uses its own family throughout the ${language} catalogue`, () => {
      expect(
        competingWords(
          JSON.stringify(catalog),
          COMPETING[language],
          PINNED[language],
        ),
      ).toEqual([]);
    });
  }

  it("would catch a value that brings the other family back", () => {
    // The exact heading the first pass left behind, and the agent noun the
    // noun-only count missed.
    expect(
      competingWords('{"title":"Zur Freigabe"}', COMPETING.de, []),
    ).toEqual(["Freigab"]);
    expect(
      competingWords('{"someone":"einem Freigebenden"}', COMPETING.de, []),
    ).toEqual(["Freigeb"]);
    expect(
      competingWords('{"bulkApprove":"Zatwierdź dokument"}', /zatwierd/i, []),
    ).toEqual(["Zatwierd"]);
    expect(
      competingWords(
        '{"title":"Zatwierdzenie dokumentu"}',
        /zatwierd/i,
        PINNED.pl,
      ),
    ).toEqual(["Zatwierd"]);
  });

  it("counts the whole file, not only the keys somebody touched", () => {
    // The release phrases are the only ones allowed to keep the other
    // family — and each only while it is still there.
    let withoutPinned = JSON.stringify(de);
    for (const phrase of PINNED.de) {
      expect(withoutPinned).toContain(phrase);
      withoutPinned = withoutPinned.split(phrase).join("");
    }

    expect(withoutPinned).not.toMatch(COMPETING.de);
  });
});
