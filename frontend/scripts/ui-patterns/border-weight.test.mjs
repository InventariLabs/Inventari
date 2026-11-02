import { describe, expect, it } from "vitest";
import borderWeight from "./border-weight.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];

describe("border-weight", () => {
  it("reports border-2 with its path:line", () => {
    const { findings, considered } = borderWeight.run(
      file(`<div>\n  <div className="rounded border-2 border-primary-500" />\n</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports every offending line separately", () => {
    const { findings } = borderWeight.run(
      file(`<a className="border-2" />\n<b className="border" />\n<c className="border-2" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:3"]);
  });

  it("accepts the 1px border and does not consider the file", () => {
    const { findings, considered } = borderWeight.run(
      file(`<div className="border border-border" />`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("does not confuse border-2 with longer utilities", () => {
    const { findings } = borderWeight.run(
      file(`<div className="border-20 border-2xl" />`),
    );

    expect(findings).toEqual([]);
  });

  it("exempts a transparent border used as geometry (switch knob inset)", () => {
    const { findings } = borderWeight.run(
      file(`<span className="h-5 w-5 border-2 border-transparent bg-white" />`),
    );

    expect(findings).toEqual([]);
  });

  it("still reports a line that only mentions transparency elsewhere", () => {
    const { findings } = borderWeight.run(
      file(`<div className="border-2 border-primary-500 bg-transparent" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });
});
