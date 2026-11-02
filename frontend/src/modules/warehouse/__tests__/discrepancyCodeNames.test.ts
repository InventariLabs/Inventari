import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * One enum value, one name.
 *
 * The same discrepancy codes lived in three branches of every catalogue:
 * `detail.discrepancyCodes`, `picking.discrepancy_code` and
 * `receiving.short.code`. English kept them in step by accident; Polish said
 * "Brak ilości" in the execution panel and "Niedobór" in the picking dialog,
 * "Blokada jakościowa" against "Wstrzymanie jakości", "Różnica
 * inwentaryzacyjna" against "Różnica w liczbie". German, French and Spanish
 * each split one or two codes the same way. The code is stored on the line
 * (`document_lines.discrepancy_code`) and read by the report and the journal,
 * so a filter by name finds a fraction of the rows and a work instruction
 * written from one screen does not match the other.
 *
 * The rule: the codes are named in exactly one branch, and the picking
 * and receiving dialogs read that branch rather than carrying their own. Two
 * branches that agree today are still two branches — the drift this guards
 * against stays invisible until the two disagree.
 *
 * Branches carrying a single code are out of scope on purpose: "OTHER" is an
 * escape hatch several different enums share (correction reasons, return
 * reasons), and naming it once per enum is not a duplicate of this set.
 */
const DISCREPANCY_CODES = [
  "SHORTAGE",
  "DAMAGE",
  "QUALITY_HOLD",
  "COUNT_VARIANCE",
  "SURPLUS",
  "OTHER",
] as const;

const CATALOGUES: Record<string, unknown> = {
  en,
  pl,
  de,
  fr,
  es,
};

type Branch = { path: string; codes: string[] };

/** Every object that names two or more discrepancy codes, as `path` + codes. */
export function codeBranches(catalog: unknown, codes: string[]): Branch[] {
  const found: Branch[] = [];
  const walk = (node: unknown, path: string) => {
    if (node == null || typeof node !== "object" || Array.isArray(node)) return;
    const object = node as Record<string, unknown>;
    const hits = Object.keys(object)
      .filter((key) => codes.includes(key) && typeof object[key] === "string")
      .sort();
    if (hits.length >= 2) found.push({ path, codes: hits });
    for (const [key, value] of Object.entries(object)) {
      walk(value, path ? `${path}.${key}` : key);
    }
  };
  walk(catalog, "");
  return found;
}

describe("the discrepancy codes have one branch of names", () => {
  for (const [lang, catalog] of Object.entries(CATALOGUES)) {
    it(`${lang} names every code, in one place`, () => {
      const branches = codeBranches(catalog, [...DISCREPANCY_CODES]);

      expect(branches.map((branch) => branch.path)).toEqual([
        "detail.discrepancyCodes",
      ]);
      expect(branches[0].codes).toEqual([...DISCREPANCY_CODES].sort());
    });
  }

  it("would catch the picking dialog inventing its own word again", () => {
    const sabotaged = {
      detail: {
        discrepancyCodes: { SHORTAGE: "Brak ilości", DAMAGE: "Uszkodzenie" },
      },
      picking: {
        discrepancy_code: { SHORTAGE: "Niedobór", DAMAGE: "Uszkodzenie" },
      },
    };

    expect(
      codeBranches(sabotaged, [...DISCREPANCY_CODES]).map(
        (branch) => branch.path,
      ),
    ).toEqual(["detail.discrepancyCodes", "picking.discrepancy_code"]);
  });

  it("leaves alone a single code another enum shares", () => {
    const otherEnums = {
      reasons: {
        correction: { codes: { OTHER: "Other" } },
        return: { codes: { OTHER: "Other" } },
      },
    };

    expect(codeBranches(otherEnums, [...DISCREPANCY_CODES])).toEqual([]);
  });
});
