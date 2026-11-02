/**
 * German copy addresses the reader one way: "Sie".
 *
 * About 180 strings spoke formally while a dozen used "du" — the launcher
 * greeting among them — and the informal imperatives ("Wähle", "Gib an")
 * read as a second voice on the same screen. The check reads the values of
 * every German catalogue, so the key names (a `dir` field) are not mistaken
 * for a pronoun.
 */
import { describe, expect, it } from "vitest";

const catalogues = import.meta.glob<Record<string, unknown>>(
  ["../locales/de/*.json", "../../modules/*/i18n/de.json"],
  { eager: true, import: "default" },
);

const INFORMAL_PRONOUNS = /\b(du|dein\w*|dich|dir|euch|eure\w*)\b/i;
// Imperatives in the informal singular; the formal form is "<verb>en Sie".
const INFORMAL_IMPERATIVES =
  /(^|[.:;—–!?]\s+)(Wähle|Gib|Füge|Klicke|Lege?|Erstelle|Öffne|Prüfe|Versuche|Lade|Trage|Tippe|Scanne|Speichere|Verwende|Nutze|Ändere|Lösche|Leere|Entferne|Starte|Warte|Kopiere|Schließe|Gehe|Setze|Bestätige|Drücke|Beginne|Benenne|Mache|Verknüpfe|Stelle|Nimm|Fotografiere|Importiere)\b/;

function* strings(value: unknown, path: string): Generator<[string, string]> {
  if (typeof value === "string") yield [path, value];
  else if (Array.isArray(value))
    for (const [i, v] of value.entries()) yield* strings(v, `${path}[${i}]`);
  else if (value && typeof value === "object")
    for (const [k, v] of Object.entries(value))
      yield* strings(v, path ? `${path}.${k}` : k);
}

describe("German catalogues address the reader as Sie", () => {
  it("has no informal pronoun or imperative in any value", () => {
    const found: string[] = [];
    for (const [file, catalogue] of Object.entries(catalogues)) {
      for (const [path, text] of strings(catalogue, "")) {
        if (INFORMAL_PRONOUNS.test(text) || INFORMAL_IMPERATIVES.test(text)) {
          found.push(`${file} ${path}: ${text.slice(0, 80)}`);
        }
      }
    }
    expect(found).toEqual([]);
  });
});
