import { describe, expect, it } from "vitest";
import {
  parseBackendBlock,
  punctuationAfterUnit,
  rivalCatalogues,
} from "./check-units-labels.mjs";

const reader = (files) => (path) => files[path];

describe("check-units-labels", () => {
  it("reads the backend mirror's block for a language", () => {
    const labels = parseBackendBlock(
      `UNIT_LABELS = {\n    'pl': {\n        'pcs': 'szt.',\n        'kg': 'kg',\n    },\n}`,
      "pl",
    );

    expect(labels).toEqual({ pcs: "szt.", kg: "kg" });
  });

  describe("a second catalogue of unit words", () => {
    it("names a module that keeps its own copy", () => {
      const files = {
        "/l/pl/common.json": JSON.stringify({ units: { pcs: "szt." } }),
        "/m/documents/i18n/pl.json": JSON.stringify({ units: { pcs: "szt." } }),
      };

      expect(rivalCatalogues(Object.keys(files), reader(files))).toEqual([
        "/m/documents/i18n/pl.json: units",
      ]);
    });

    it("names the one keyed by the unit's name", () => {
      const files = {
        "/l/pl/items.json": JSON.stringify({ uomSymbols: { Piece: "szt." } }),
      };

      expect(rivalCatalogues(Object.keys(files), reader(files))).toEqual([
        "/l/pl/items.json: uomSymbols",
      ]);
    });

    it("leaves the canonical one, and the names catalogue, alone", () => {
      const files = {
        "/l/pl/common.json": JSON.stringify({ units: { pcs: "szt." } }),
        "/l/pl/items.json": JSON.stringify({ uomNames: { Piece: "Sztuka" } }),
      };

      expect(rivalCatalogues(Object.keys(files), reader(files))).toEqual([]);
    });
  });

  describe("punctuation straight after a unit", () => {
    it("names the sentence that produced 'Plan 3 szt..'", () => {
      const files = {
        "/m/documents/i18n/pl.json": JSON.stringify({
          detail: {
            executionMeta:
              "Plan {{expected}} {{unit}}. Pozostało {{remaining}}",
          },
        }),
      };

      expect(punctuationAfterUnit(Object.keys(files), reader(files))).toEqual([
        "/m/documents/i18n/pl.json: detail.executionMeta",
      ]);
    });

    it("catches a comma and a semicolon the same way", () => {
      const files = {
        "/a.json": JSON.stringify({ a: "{{uom}}, and", b: "{{unit}}; then" }),
      };

      expect(punctuationAfterUnit(Object.keys(files), reader(files))).toEqual([
        "/a.json: a",
        "/a.json: b",
      ]);
    });

    it("says nothing when the unit does not end the clause", () => {
      const files = {
        "/a.json": JSON.stringify({
          a: "Plan {{expected}} {{unit}} · pozostało {{remaining}} {{unit}}",
          b: "Expected {{expected}} {{uom}} — how much was picked?",
        }),
      };

      expect(punctuationAfterUnit(Object.keys(files), reader(files))).toEqual(
        [],
      );
    });
  });
});
