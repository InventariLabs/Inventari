import { describe, expect, it } from "vitest";

import i18n from "@/test/mocks/i18n";
import type { TranslateFn } from "@/types/i18n";

import {
  itemToResult,
  itemsToResults,
  matchOf,
  rankItemsByRelevance,
} from "../useCommandPaletteSearch";
import type { Item } from "@/types";

const t = i18n.t.bind(i18n) as unknown as TranslateFn;

function item(overrides: Partial<Item> & { name: string }): Item {
  return {
    id: overrides.id ?? overrides.name.toLowerCase().replace(/\s+/g, "-"),
    location_id: "loc-1",
    category_id: null,
    brand: null,
    description: null,
    weight: null,
    uom: null,
    quantity: 3,
    added_date: "2026-09-01",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    ...overrides,
  } as Item;
}

/** The shape of the reported case: "mak" against a shelf holding honeys,
 *  flours and the pastas the reader was after. */
const SHELF: Item[] = [
  item({ name: "Miód wielokwiatowy", brand: "Przysmakow" }),
  item({ name: "Mąka ziemniaczana" }),
  item({ name: "Serek wiejski", brand: "Twoj Smak" }),
  item({ name: "Miód wielokwiatowy", brand: "Przysmakow", id: "honey-2" }),
  item({ name: "Mąka pszenna typ 550" }),
  item({ name: "Makaron penne" }),
  item({ name: "Makaron spaghetti 500g" }),
  item({ name: "Makaron fusilli" }),
];

describe("rankItemsByRelevance", () => {
  it("puts a name hit ahead of a brand hit for the same query", () => {
    const ranked = rankItemsByRelevance(SHELF, "mak");

    const titles = ranked.map((entry) => entry.name);
    // The pastas — the name the reader meant — come before the honeys and
    // the quark, whose brands merely carry the string.
    expect(titles.indexOf("Makaron penne")).toBeLessThan(
      titles.indexOf("Miód wielokwiatowy"),
    );
    expect(titles.indexOf("Makaron fusilli")).toBeLessThan(
      titles.indexOf("Serek wiejski"),
    );
  });

  it("ranks a name typed from its beginning above a name carrying it", () => {
    // The carrier arrives first on the wire, so only the rank can demote it.
    const ranked = rankItemsByRelevance(
      [
        item({ name: "Zapiekanka z mąką" }),
        item({ name: "Mąka ziemniaczana" }),
      ],
      "mąka",
    );

    expect(ranked[0].name).toBe("Mąka ziemniaczana");
  });

  it("keeps the server's own order inside one rank", () => {
    const [first, second] = [
      item({ name: "Makaron A" }),
      item({ name: "Makaron B" }),
    ];
    // Reversed on the wire, intact after the rank: the stable sort decides
    // which field won, not how the server ordered equals.
    expect(rankItemsByRelevance([first, second], "mak")).toEqual([
      first,
      second,
    ]);
  });

  it("ranks a product code that lives on the template as a code hit", () => {
    // The measured shape: a record created through a scan keeps
    // its own barcode empty and the code rides on the template — on the wire
    // (ProductTemplate.barcode), so the client owes it the code rank, not
    // the shrug.
    const scanned = item({
      name: "Woda mineralna 0,5l",
      template: {
        id: "tpl-water",
        name: "Woda mineralna 0,5l",
        barcode: "5901234000017",
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      },
    });
    expect(matchOf(scanned, "5901234").field).toBe("code");
  });

  it("ranks a hit it cannot attribute last", () => {
    const honey = item({ name: "Miód wielokwiatowy", brand: "Przysmakow" });
    // No field this record carries — its own or its template's — holds the
    // string, so the row refuses to invent a reason and ranks last.
    expect(matchOf(honey, "5901234").field).toBe("unattributed");
  });
});

describe("itemToResult — what the row admits", () => {
  it("says the record hit on its brand, not its name", async () => {
    const honey = SHELF[0];
    const result = itemToResult(honey, t, "mak");
    expect(result.subtitle).toBe("matched on brand: Przysmakow");
  });

  it("says the record hit on the product code the template carries", async () => {
    // A scan-created record keeps its own barcode empty; the code the reader
    // typed sits on the template. The row names it like any other code hit —
    // silence here is what told the reader the hit was nobody's fault.
    const { withLanguage } = await import("@/test/mocks/i18n");
    const scanned = item({
      name: "Woda mineralna 0,5l",
      template: {
        id: "tpl-water",
        name: "Woda mineralna 0,5l",
        barcode: "5901234000017",
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      },
    });
    await withLanguage("pl", () => {
      const result = itemToResult(scanned, t, "5901234000017");
      expect(result.subtitle).toBe("trafienie po kodzie: 5901234000017");
    });
  });

  it("says the record hit on its serial number", async () => {
    const { withLanguage } = await import("@/test/mocks/i18n");
    const asset = item({
      name: "Laptop FD-88",
      serial_number: "SN-MAK-0001",
      brand: null,
    });
    await withLanguage("en", () => {
      const result = itemToResult(asset, t, "mak");
      expect(result.subtitle).toBe("matched on serial number: SN-MAK-0001");
    });
  });

  it("gives twin names something to tell them apart", async () => {
    const { withLanguage } = await import("@/test/mocks/i18n");
    const big = item({ name: "Miód wielokwiatowy", quantity: "5" });
    const small = item({ name: "Miód wielokwiatowy", quantity: "0.5" });

    await withLanguage("en", () => {
      const first = itemToResult(big, t, "miód").subtitle;
      const second = itemToResult(small, t, "miód").subtitle;
      expect(first).not.toBe(second);
      expect(first).toContain("5");
      expect(second).toContain("0.5");
    });
  });

  it("tells same-brand twins apart, by name and by brand alike", async () => {
    // The review's shape: one product bought in two batches. The brand line
    // both rows print identically, and the quantity — the only thing the
    // pair disagrees about — never reached the row. The list reads its own
    // ties and says the quantity where two rows would otherwise draw the
    // same characters.
    const { withLanguage } = await import("@/test/mocks/i18n");
    const big = item({
      id: "honey-big",
      name: "Miód wielokwiatowy",
      brand: "Przysmakow",
      quantity: "12",
    });
    const small = item({
      id: "honey-small",
      name: "Miód wielokwiatowy",
      brand: "Przysmakow",
      quantity: "3",
    });

    await withLanguage("en", () => {
      for (const query of ["miód", "przysmakow"]) {
        const [first, second] = itemsToResults([big, small], t, query);
        expect(first.subtitle).not.toBe(second.subtitle);
        expect(first.subtitle).toContain("12");
        expect(second.subtitle).toContain("3");
      }
    });
  });

  it("leaves a row standing alone exactly as it read it", async () => {
    // Discrimination is for ties: a single hit keeps the clean line, no
    // quantity bolted onto a brand reason that needed no help.
    const honey = item({ name: "Miód wielokwiatowy", brand: "Przysmakow" });
    expect(itemsToResults([honey], t, "mak")[0].subtitle).toBe(
      "matched on brand: Przysmakow",
    );
  });

  it("says how much it holds when there is nothing more specific", async () => {
    const jam = item({ name: "Konfitura", quantity: "2" });
    const result = itemToResult(jam, t, "konf");
    expect(result.subtitle).toBe("2");
  });
});
