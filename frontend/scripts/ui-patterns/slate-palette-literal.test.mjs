import { describe, expect, it } from "vitest";
import slatePaletteLiteral from "./slate-palette-literal.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("slate-palette-literal", () => {
  it("reports a slate class in a className and in a lookup map", () => {
    const { findings } = slatePaletteLiteral.run(
      files(`<span className="bg-slate-100 text-slate-700" />
      const TONE = { other: "border-slate-200" };`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:1", "Fixture.tsx:2"]);
  });

  it("leaves the gray scale and other palettes alone", () => {
    const { findings } = slatePaletteLiteral.run(
      files(`<span className="bg-gray-100 text-gray-700 bg-zinc-100" />`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read a comment as the mistake", () => {
    const { findings } = slatePaletteLiteral.run(
      files(`// bg-slate-100 was the old grey
      <span className="bg-gray-100" />`),
    );

    expect(findings).toEqual([]);
  });

  it("lets an identity swatch stay when it says why", () => {
    const { findings } = slatePaletteLiteral.run(
      files(`{/* ui-pattern: palette-identity — the swatch shows the colour the user chose */}
      const SWATCH = { slate: "bg-slate-400" };`),
    );

    expect(findings).toEqual([]);
  });
});
