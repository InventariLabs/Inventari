import { describe, expect, it } from "vitest";
import successPaletteLiteral from "./success-palette-literal.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("success-palette-literal", () => {
  it("reports an emerald class in a className", () => {
    const { findings } = successPaletteLiteral.run(
      files(`<span className="h-2 w-2 rounded-full bg-emerald-500" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("reports a green class sitting in a lookup map, not a className", () => {
    const { findings } = successPaletteLiteral.run(
      files(`const DOT = {
        success: "bg-green-500",
        info: "bg-blue-500",
      };`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });

  it("reports a variant-prefixed literal", () => {
    const { findings } = successPaletteLiteral.run(
      files(`<div className="bg-green-50 hover:bg-green-100" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:1"]);
  });

  it("leaves the success token and unrelated palette colours alone", () => {
    const { findings } = successPaletteLiteral.run(
      files(`<div className="bg-success-50 text-success-600 border-success-300" />
      <span className="bg-blue-500 text-amber-600" />`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read the prose explaining the mistake as the mistake", () => {
    const { findings } = successPaletteLiteral.run(
      files(`/**
       * Use success-* here; bg-emerald-500 is what this replaced.
       */
      // text-green-600 was the old spelling.
      <span className="text-success-600" />`),
    );

    expect(findings).toEqual([]);
  });

  it("honours a palette-identity exception that carries its reason", () => {
    const { findings } = successPaletteLiteral.run(
      files(`{/* ui-pattern: palette-identity — the swatch shows the colour the
          user picked as their widget's identity, not a status */}
      const SWATCH = { green: "bg-green-500" };`),
    );

    expect(findings).toEqual([]);
  });

  it("rejects an exception whose reason is not a sentence", () => {
    const { findings } = successPaletteLiteral.run(
      files(`{/* ui-pattern: palette-identity — looks nice */}
      const SWATCH = { green: "bg-green-500" };`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });
});
