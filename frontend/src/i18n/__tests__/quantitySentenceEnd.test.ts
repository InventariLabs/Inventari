/**
 * A unit abbreviation carries its own full stop ("pcs.", "szt."), so a
 * sentence that ends on a quantity must not add another: "Brakuje 1 szt.."
 * The quantity placeholders end up last in a sentence in some languages and
 * not in others, so the reword is per language and the check runs over every
 * catalogue the app ships.
 */
import { describe, expect, it } from "vitest";

const catalogues = import.meta.glob<Record<string, unknown>>(
  ["../locales/*/*.json", "../../modules/*/i18n/*.json"],
  { eager: true, import: "default" },
);

const QUANTITY_THEN_STOP = /\{\{(?:quantity|remaining)\}\}\.(?:\s|$)/;

function strings(node: unknown, path: string, out: [string, string][]) {
  if (typeof node === "string") out.push([path, node]);
  else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      strings(value, `${path}.${key}`, out);
    }
  }
}

describe("translated sentences", () => {
  it("do not put a full stop after a quantity that ends in a unit", () => {
    const offenders: string[] = [];
    for (const [file, catalogue] of Object.entries(catalogues)) {
      const found: [string, string][] = [];
      strings(catalogue, file, found);
      for (const [path, text] of found) {
        if (QUANTITY_THEN_STOP.test(text)) offenders.push(`${path}: ${text}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
