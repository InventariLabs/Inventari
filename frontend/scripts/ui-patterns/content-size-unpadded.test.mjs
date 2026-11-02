import { describe, expect, it } from "vitest";
import contentSizeUnpadded from "./content-size-unpadded.mjs";

const file = (text) => [{ path: "modules/things/ThingPage.tsx", text }];
const run = (text) => contentSizeUnpadded.run(file(text)).findings;

describe("content-size-unpadded", () => {
  it("flags a content-sized button that states no vertical rhythm", () => {
    expect(run(`<Button size="content">Open</Button>`)).toEqual([
      "modules/things/ThingPage.tsx:1",
    ]);
    expect(
      run(`<div>\n  <Button size="contentSm" className="px-0">Open</Button>\n</div>`),
    ).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("does not take h-auto for a stated height — it is what the size already is", () => {
    for (const className of ["h-auto", "h-auto px-0", "md:h-10 h-auto"]) {
      expect(
        run(`<Button size="content" className="${className}">Open</Button>`),
        className,
      ).toEqual([
        "modules/things/ThingPage.tsx:1",
      ]);
    }
  });

  it("accepts a stated height, floor or padding", () => {
    for (const className of ["h-11", "min-h-11", "py-2", "p-2", "h-[44px]", "h-full"]) {
      expect(
        run(`<Button size="content" className="${className}">Open</Button>`),
        className,
      ).toEqual([]);
    }
  });

  it("asks each branch of a ternary: the bare one still renders 21px", () => {
    expect(
      run(
        `<Button size="content" className={on ? "py-2" : "px-0"}>Open</Button>`,
      ),
    ).toEqual(["modules/things/ThingPage.tsx:1"]);
  });

  it("ignores buttons of any other size", () => {
    const { findings, considered } = contentSizeUnpadded.run(
      file(`<Button size="sm">Open</Button><Button>Plain</Button>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });
});
