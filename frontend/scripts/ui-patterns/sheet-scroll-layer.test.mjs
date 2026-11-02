import { describe, expect, it } from "vitest";
import sheetScrollLayer from "./sheet-scroll-layer.mjs";

const file = (text, path = "modules/things/ThingSheet.tsx") => [{ path, text }];

describe("sheet-scroll-layer", () => {
  it("flags a Sheet whose body has no scroll layer (path only, no line)", () => {
    const { considered, findings } = sheetScrollLayer.run(
      file(`<Sheet open={open}>
  <SheetContent>
    <div>long body</div>
  </SheetContent>
</Sheet>`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/ThingSheet.tsx"]);
  });

  it("accepts a Sheet that wraps its body in SheetBody", () => {
    const { considered, findings } = sheetScrollLayer.run(
      file(`<Sheet>
  <SheetContent><SheetBody>x</SheetBody></SheetContent>
</Sheet>`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual([]);
  });

  it("accepts a Sheet with its own overflow-y-auto or overflow-auto region", () => {
    for (const cls of ["overflow-y-auto", "overflow-auto"]) {
      const { findings } = sheetScrollLayer.run(
        file(`<Sheet><div className="${cls}">x</div></Sheet>`),
      );
      expect(findings).toEqual([]);
    }
  });

  it("recognises a bare <Sheet> at end of text and <Sheet> followed by a newline", () => {
    expect(sheetScrollLayer.run(file("<Sheet")).findings).toEqual([
      "modules/things/ThingSheet.tsx",
    ]);
    expect(sheetScrollLayer.run(file("<Sheet\n  open />")).findings).toEqual([
      "modules/things/ThingSheet.tsx",
    ]);
  });

  it("does not match SheetContent, SheetHeader or similar names alone", () => {
    const { considered, findings } = sheetScrollLayer.run(
      file(`<SheetContent><SheetHeader>x</SheetHeader></SheetContent>`),
    );

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });

  it("reports one finding per file, across several files", () => {
    const { considered, findings } = sheetScrollLayer.run([
      { path: "a.tsx", text: "<Sheet>x</Sheet>" },
      { path: "b.tsx", text: "<Sheet><SheetBody>x</SheetBody></Sheet>" },
      { path: "c.tsx", text: "<div />" },
    ]);

    expect(considered).toBe(2);
    expect(findings).toEqual(["a.tsx"]);
  });
});
