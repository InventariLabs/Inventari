import { describe, expect, it } from "vitest";

import { withLanguage, tFor } from "@/test/mocks/i18n";
import {
  partialPackage,
  partialPackageOfSize,
  partialPackageSentence,
} from "./partialPackage";

const pieces = { category_name: "Unit" };
const twoKilos = { value: 2, symbol: "kg" };

describe("partialPackage", () => {
  it("restates 0.75 pcs on a 2 kg card as 1.5 kg", () => {
    expect(
      partialPackage({
        quantity: "0.750",
        uom: pieces,
        pieceMeasure: twoKilos,
      }),
    ).toMatchObject({ amount: 1.5, symbol: "kg", belowOnePiece: true });
  });

  it("reads a whole number of pieces as it always did", () => {
    expect(
      partialPackage({
        quantity: "3.000",
        uom: pieces,
        pieceMeasure: twoKilos,
      }),
    ).toBeNull();
  });

  it("says nothing for a card that records no weight or volume", () => {
    expect(
      partialPackage({ quantity: "0.5", uom: pieces, pieceMeasure: null }),
    ).toBeNull();
  });

  it("leaves a record kept in a measured unit alone", () => {
    expect(
      partialPackage({
        quantity: "0.5",
        uom: { category_name: "Weight" },
        pieceMeasure: twoKilos,
      }),
    ).toBeNull();
  });

  it("does not treat a pack as a piece", () => {
    expect(
      partialPackage({
        quantity: "0.5",
        uom: { category_name: "Pack" },
        pieceMeasure: twoKilos,
      }),
    ).toBeNull();
  });

  it("gives a total, not a remainder, above one piece", () => {
    expect(
      partialPackage({ quantity: "2.5", uom: pieces, pieceMeasure: twoKilos }),
    ).toMatchObject({ amount: 5, belowOnePiece: false });
  });
});

describe("partialPackageSentence", () => {
  const pack = partialPackage({
    quantity: "0.75",
    uom: pieces,
    pieceMeasure: twoKilos,
  })!;

  it("reads '1.5 kg left of 2 kg'", () => {
    const t = tFor("common");
    expect(partialPackageSentence(t, pack)).toBe("1.5 kg left of 2 kg");
    expect(partialPackageOfSize(t, pack)).toBe("of 2 kg");
  });

  it("reads in Polish", async () => {
    await withLanguage("pl", () => {
      const t = tFor("common");
      expect(partialPackageSentence(t, pack)).toBe("zostało 1,5 kg z 2 kg");
    });
  });
});
