import { describe, expect, it } from "vitest";
import footerHalfWidth from "./footer-half-width.mjs";

const file = (text) => [{ path: "Fixture.tsx", text }];

describe("footer-half-width", () => {
  it("reports flex-1 on a button inside a named footer", () => {
    const { findings, considered } = footerHalfWidth.run(
      file(`<DialogFooter>
  <Button className="flex-1">Save</Button>
</DialogFooter>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports flex-1 in an overlay row shaped like a footer", () => {
    const { findings } = footerHalfWidth.run(
      file(`<Sheet>
<div className="flex justify-end gap-2 border-t">
  <Button className="flex-1">Save</Button>
</div>
</Sheet>`),
    );

    expect(findings).toEqual(["Fixture.tsx:3"]);
  });

  it("reports a footer-shaped row pinned to the page", () => {
    const { findings } = footerHalfWidth.run(
      file(`<div className="sticky bottom-0 border-t">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });

  it("reports flex-1 buttons in a bare flex row of an overlay", () => {
    const { findings } = footerHalfWidth.run(
      file(`<Dialog open>
<div className="flex gap-3 pt-1">
  <Button variant="outline" className="flex-1">Cancel</Button>
  <Button type="submit" className="flex-1">Save</Button>
</div>
</Dialog>`),
    );

    expect(findings).toEqual(["Fixture.tsx:3", "Fixture.tsx:4"]);
  });

  it("leaves a bare row where a button sits beside a field", () => {
    const { findings } = footerHalfWidth.run(
      file(`<Dialog open>
<div className="flex gap-2">
  <Input />
  <Button className="flex-1">Add</Button>
</div>
</Dialog>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a button released from sm: up", () => {
    const { findings } = footerHalfWidth.run(
      file(`<SheetFooter>
  <Button className="flex-1 sm:flex-none">Save</Button>
  <Button className="flex-1 md:w-auto">Cancel</Button>
</SheetFooter>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a border-t card row that is not in an overlay or pinned", () => {
    const { findings } = footerHalfWidth.run(
      file(`<div className="flex border-t">
  <Button className="flex-1">Open</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves flex-1 on a button that is not near a footer", () => {
    const { findings } = footerHalfWidth.run(
      file(`<div className="flex">
  <Input />
  <Button className="flex-1">Filter</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a footer button without flex-1", () => {
    const { findings, considered } = footerHalfWidth.run(
      file(`<SheetFooter><Button className="px-4">Save</Button></SheetFooter>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });
});
