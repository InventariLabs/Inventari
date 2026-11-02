import { describe, expect, it } from "vitest";
import footerActionRows from "./footer-action-rows.mjs";

const file = (text) => [{ path: "Fixture.tsx", text }];

describe("footer-action-rows", () => {
  it("reports a footer holding two action rows at the footer's line", () => {
    const { findings, considered } = footerActionRows.run(
      file(`<Sheet>
<SheetFooter>
  <SheetActions><Button>Cancel</Button></SheetActions>
  <SheetActions><Button>Save</Button></SheetActions>
</SheetFooter>
</Sheet>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports a destructive button at the button's line", () => {
    for (const variant of ["ghostDanger", "destructive", "danger"]) {
      const { findings } = footerActionRows.run(
        file(`<SheetFooter>
  <SheetActions>
    <Button variant="${variant}">Delete</Button>
  </SheetActions>
</SheetFooter>`),
      );

      expect(findings).toEqual(["Fixture.tsx:3"]);
    }
  });

  it("leaves a single row of Cancel and a primary action", () => {
    const { findings } = footerActionRows.run(
      file(`<SheetFooter>
  <SheetActions>
    <Button variant="secondary">Cancel</Button>
    <Button variant="primary">Save</Button>
  </SheetActions>
</SheetFooter>`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores a destructive button outside any footer", () => {
    const { findings, considered } = footerActionRows.run(
      file(`<Button variant="destructive">Delete</Button>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("ignores a footer that is only in a comment", () => {
    const { findings } = footerActionRows.run(
      file(`{/* <SheetFooter><SheetActions/><SheetActions/></SheetFooter> */}`),
    );

    expect(findings).toEqual([]);
  });

  it("accepts an exception with a reason of five words", () => {
    const { findings } = footerActionRows.run(
      file(`{/* ui-pattern: footer-action — the sheet is the confirmation step */}
<SheetFooter>
  <SheetActions><Button variant="destructive">Delete</Button></SheetActions>
</SheetFooter>`),
    );

    expect(findings).toEqual([]);
  });

  it("rejects an exception whose reason is too short", () => {
    const { findings } = footerActionRows.run(
      file(`{/* ui-pattern: footer-action — because */}
<SheetFooter>
  <SheetActions><Button variant="destructive">Delete</Button></SheetActions>
</SheetFooter>`),
    );

    expect(findings).toEqual(["Fixture.tsx:3"]);
  });

  it("lets an exception excuse two rows", () => {
    const { findings } = footerActionRows.run(
      file(`{/* ui-pattern: footer-action — both rows belong to this one step */}
<SheetFooter>
  <SheetActions />
  <SheetActions />
</SheetFooter>`),
    );

    expect(findings).toEqual([]);
  });
});
