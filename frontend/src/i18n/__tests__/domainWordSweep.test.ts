/**
 * Wording that docs/MODULE_NAMES.md ("Domain vocabulary") settled for words the
 * English gate cannot read: the place stock is kept is Lagerort in German
 * everywhere, a product's stock row is a record, and the work-mode card calls
 * what it lists a module and the page it sends to by that page's title.
 */
import { describe, expect, it } from "vitest";

import commonEn from "../locales/en/common.json";
import commonPl from "../locales/pl/common.json";
import inventoryEn from "../../modules/inventory/i18n/en.json";
import inventoryPl from "../../modules/inventory/i18n/pl.json";

const germanCatalogues = {
  ...import.meta.glob("../locales/de/*.json", {
    eager: true,
    import: "default",
  }),
  ...import.meta.glob("../../modules/*/i18n/de.json", {
    eager: true,
    import: "default",
  }),
};

describe("domain word sweep", () => {
  it("never calls a stock place Standort in German", () => {
    const files = Object.keys(germanCatalogues);
    expect(files.length).toBeGreaterThan(10);
    const offenders = Object.entries(germanCatalogues)
      .filter(([, catalogue]) => /standort/i.test(JSON.stringify(catalogue)))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });

  it("counts the stock register in records, not stock entries", () => {
    expect(inventoryEn.stock.rows_one).toBe("record");
    expect(inventoryEn.stock.rows_other).toBe("records");
    expect(inventoryPl.stock.rows_one).toBe("rekord");
  });

  it("names the module page as the page is titled and keeps one word on the work-mode card", () => {
    expect(commonPl.settings.focus.enableLink).toContain(
      commonPl.appStore.title.replace(/y$/, ""),
    );
    expect(commonPl.settings.focus.enableLink).not.toMatch(/sklep/i);
    for (const focus of [commonEn.settings.focus, commonPl.settings.focus]) {
      expect(`${focus.empty} ${focus.emptyHint}`).not.toMatch(
        /\bapps?\b|aplikacj/i,
      );
    }
  });
});
