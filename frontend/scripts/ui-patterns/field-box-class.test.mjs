import { describe, expect, it } from "vitest";
import fieldBoxClass from "./field-box-class.mjs";

const file = (text) => [{ path: "Fixture.tsx", text }];

describe("field-box-class", () => {
  it("reports a width in a Textarea's className", () => {
    const { findings, considered } = fieldBoxClass.run(
      file(`<div>
        <Textarea className="max-w-md" />
      </div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports a margin, a flex share and a grid span", () => {
    const { findings } = fieldBoxClass.run(
      file(`<Input className="mt-2" />
<Select className="flex-1" />
<DateInput className="col-span-2" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:2", "Fixture.tsx:3"]);
  });

  it("reports a responsive variant of a box class", () => {
    const { findings } = fieldBoxClass.run(
      file(`<Input className="h-9 xs:w-16" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("leaves control classes and wrapperClassName alone", () => {
    const { findings } = fieldBoxClass.run(
      file(`<Input className="h-9 px-3 text-sm w-full" wrapperClassName="max-w-md" />
<Select className="font-mono" />
<Input />`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores components that are not form controls", () => {
    const { findings } = fieldBoxClass.run(
      file(`<Card className="max-w-md mt-2" />`),
    );

    expect(findings).toEqual([]);
  });
});
