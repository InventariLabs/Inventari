import { describe, expect, it } from "vitest";
import detector from "./disclosure-indicator.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];
const ds = (text) => file(text, "components/ui/Select.tsx");

describe("disclosure-indicator", () => {
  it("reports a bare <select> anywhere in the corpus", () => {
    const { findings, considered } = detector.run(
      file(`<div>\n  <select className="h-10 px-2">\n  </select>\n</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports a <select> with no className at all", () => {
    expect(detector.run(file(`<select></select>`)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  it("accepts a <select> with appearance-none", () => {
    const { findings } = detector.run(
      file(`<select className="appearance-none pr-10 h-10"></select>`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores a <select> mentioned only in comments", () => {
    const { findings, considered } = detector.run(
      file(`// the old <select> was removed\n/* <select className="x"> */\n<div />`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("reports a ChevronDown at the wrong size in the design system", () => {
    const { findings } = detector.run(
      ds(`<button className="h-10">\n  <ChevronDown size={16} />\n</button>`),
    );

    expect(findings).toEqual(["components/ui/Select.tsx:2"]);
  });

  it("reports a ChevronDown without a size prop", () => {
    const { findings } = detector.run(ds(`<ChevronDown className="x" />`));

    expect(findings).toEqual(["components/ui/Select.tsx:1"]);
  });

  it("accepts size 18 on a control of the shared height", () => {
    for (const h of ["h-9", "h-10", "h-11", "min-h-10", "h-[calc(2rem+2px)]"]) {
      const { findings } = detector.run(
        ds(`<button className="${h} flex">\n  <ChevronDown size={18} />\n</button>`),
      );
      expect(findings).toEqual([]);
    }
  });

  it("reports size 18 when its trigger states no allowed height", () => {
    const { findings } = detector.run(
      ds(`<SelectTrigger className="h-7">\n  <ChevronDown size={18} />\n</SelectTrigger>`),
    );

    expect(findings).toEqual(["components/ui/Select.tsx:2"]);
  });

  it("accepts size 18 when no control is in reach (decoration)", () => {
    const { findings, considered } = detector.run(
      ds(`<span><ChevronDown size={18} /></span>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(1);
  });

  it("does not police ChevronDown outside components/ui/", () => {
    const { findings, considered } = detector.run(
      file(`<ChevronDown size={12} />`, "pages/Tree.tsx"),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("ignores a ChevronDown in a comment", () => {
    const { findings } = detector.run(ds(`// <ChevronDown size={12} />\n<div />`));

    expect(findings).toEqual([]);
  });
});
