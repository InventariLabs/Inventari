import { afterEach, describe, expect, it } from "vitest";
import {
  parseBackendBlock,
  punctuationAfterUnit,
  rivalCatalogues,
} from "./check-units-labels.mjs";
import { makeRepo, runGate } from "./gate-fixture.mjs";

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

  describe("as the process `npm run check:units-labels` starts", () => {
    let repo;
    afterEach(() => repo?.cleanup());

    const run = (screenLabel, args) => {
      repo = makeRepo();
      const languages = ["en", "pl", "de", "es", "fr"];
      const mirror = languages
        .map((l) => `    '${l}': {\n        'kg': 'kg',\n    },`)
        .join("\n");
      const files = {
        "backend/app/i18n/_units.py": `UNIT_LABELS = {\n${mirror}\n}\n`,
        "frontend/src/modules/.keep": "",
      };
      for (const l of languages) {
        files[`frontend/src/i18n/locales/${l}/common.json`] = {
          units: { kg: l === "pl" ? screenLabel : "kg" },
        };
      }
      repo.write(files);
      return runGate(repo, "check-units-labels.mjs", { args });
    };

    it("names the drift under --quiet, which silences only the success line", () => {
      const drifted = run("kilo", ["--quiet"]);
      expect(drifted.status).toBe(1);
      expect(drifted.stderr).toContain(
        "pl: 'kg' is 'kg' in the backend mirror but 'kilo' on the screen",
      );

      const clean = run("kg", ["--quiet"]);
      expect(clean.status).toBe(0);
      expect(clean.stdout).toBe("");
    });
  });
});
