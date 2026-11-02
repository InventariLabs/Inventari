import { describe, expect, it } from "vitest";
import detector, { scan } from "./button-size-override.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];

describe("button-size-override", () => {
  it("reports a plain height on a default-size Button", () => {
    const { findings, considered } = detector.run(
      file(`<div>\n  <Button className="h-8 px-2">x</Button>\n</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports height on explicit sm and md sizes", () => {
    for (const size of ["sm", "md"]) {
      const { findings } = detector.run(
        file(`<Button size="${size}" className="h-6" />`),
      );
      expect(findings).toEqual(["Fixture.tsx:1"]);
    }
  });

  it("reports width and size-* on an icon Button, but not width on default", () => {
    expect(
      detector.run(file(`<Button size="icon" className="w-8" />`)).findings,
    ).toEqual(["Fixture.tsx:1"]);
    expect(
      detector.run(file(`<Button size="icon" className="size-8" />`)).findings,
    ).toEqual(["Fixture.tsx:1"]);
    expect(detector.run(file(`<Button className="w-8" />`)).findings).toEqual([]);
  });

  it("reports min-/max- height and arbitrary values", () => {
    expect(
      detector.run(file(`<Button className="min-h-[3rem]" />`)).findings,
    ).toEqual(["Fixture.tsx:1"]);
    expect(
      detector.run(file(`<Button className="max-h-10" />`)).findings,
    ).toEqual(["Fixture.tsx:1"]);
  });

  it("reads a className inside cn() and a tag with an arrow handler", () => {
    const { findings } = detector.run(
      file(`<Button onClick={() => close()} className={cn("a", "h-9")}>x</Button>`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("accepts sizes free of responsive modifiers", () => {
    const { findings, considered } = detector.run(
      file(
        `<Button size="lg" className="h-14" />\n<Button size="iconSm" className="h-8 w-8" />\n<Button size="inline" className="h-6" />`,
      ),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("accepts a Button with no className or no dimension class", () => {
    const { findings } = detector.run(
      file(`<Button>x</Button>\n<Button className="px-2 text-sm" />`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores a responsive-only override", () => {
    const { findings } = detector.run(file(`<Button className="md:h-12" />`));

    expect(findings).toEqual([]);
  });

  it("accepts a call site that answers the variant at md too", () => {
    const { findings } = detector.run(
      file(`<Button className="h-auto md:h-auto" />`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores height classes on elements that are not Button", () => {
    const { findings } = detector.run(file(`<div className="h-8" />`));

    expect(findings).toEqual([]);
  });

  it("scan() narrows to the sizes it is given", () => {
    const text = `<Button className="h-8" />\n<Button size="icon" className="h-8" />`;

    expect(scan(file(text)).findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:2"]);
    expect(scan(file(text), ["icon"]).findings).toEqual(["Fixture.tsx:2"]);
  });
});
