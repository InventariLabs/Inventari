import { describe, expect, it } from "vitest";
import labelLineBox from "./label-line-box.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];

describe("label-line-box", () => {
  it("reports a label with no display class", () => {
    const { findings, considered } = labelLineBox.run(
      file(`<div>
  <label className="text-sm font-medium">Name</label>
</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports a label with no className at all", () => {
    const { findings } = labelLineBox.run(file(`<label htmlFor="a">A</label>`));

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("leaves a label that settles its display box", () => {
    for (const cls of ["block", "flex", "inline-flex", "grid", "sr-only", "hidden", "absolute"]) {
      const { findings } = labelLineBox.run(
        file(`<label className="text-sm ${cls}">Name</label>`),
      );

      expect(findings).toEqual([]);
    }
  });

  it("resolves a same-file constant", () => {
    const text = `const fieldLabel = "block text-sm";
const plain = "text-sm";
<label className={fieldLabel}>A</label>
<label className={plain}>B</label>`;
    const { findings } = labelLineBox.run(file(text));

    expect(findings).toEqual(["Fixture.tsx:4"]);
  });

  it("judges FIELD_LABEL_CLASS by the shared definition", () => {
    const caller = {
      path: "Form.tsx",
      text: `<label className={FIELD_LABEL_CLASS}>A</label>`,
    };
    const withBlock = {
      path: "src/components/ui/fieldLabel.tsx",
      text: `export const FIELD_LABEL_CLASS = "block text-sm";`,
    };
    const withoutBlock = {
      path: "src/components/ui/fieldLabel.tsx",
      text: `export const FIELD_LABEL_CLASS = "text-sm";`,
    };

    expect(labelLineBox.run([caller, withBlock]).findings).toEqual([]);
    expect(labelLineBox.run([caller, withoutBlock]).findings).toEqual([
      "Form.tsx:1",
    ]);
  });

  it("ignores a label that is only in a comment", () => {
    const { findings } = labelLineBox.run(
      file(`{/* <label className="text-sm">Name</label> */}`),
    );

    expect(findings).toEqual([]);
  });
});
