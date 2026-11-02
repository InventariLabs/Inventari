import { describe, expect, it } from "vitest";
import flex1InAColumn from "./flex-1-in-a-column.mjs";

const file = (text, path = "modules/things/ThingPage.tsx") => [{ path, text }];

describe("flex-1-in-a-column", () => {
  /** The attestation row, verbatim in shape — handler arrow included. */
  const attestationRow = `<div className="flex gap-3 flex-col sm:flex-row">
  <Button
    className="flex-1"
    onClick={() => confirmMutation.mutate(undefined, { onSuccess: close })}
    disabled={pending}
  >
    Confirm
  </Button>
  <Button variant="outline" className="flex-1" onClick={() => dispute()}>
    Report a problem
  </Button>
</div>`;

  it("flags every button in a row that is a column below sm", () => {
    const { findings } = flex1InAColumn.run(file(attestationRow));

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:2",
      "modules/things/ThingPage.tsx:9",
    ]);
  });

  it("flags the same shape with the direction written first", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col sm:flex-row gap-3 pt-2">
  <Button type="button" variant="outline" className="flex-1">Cancel</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("flags a column with no breakpoint at all, where every width collapses", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col gap-3">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("accepts the fix: the width carries the fill, the height stays pinned", () => {
    const { findings } = flex1InAColumn.run(
      file(
        attestationRow.replaceAll(
          'className="flex-1"',
          'className="w-full sm:w-auto"',
        ),
      ),
    );

    expect(findings).toEqual([]);
  });

  it("accepts flex-1 in a row, where it is a width claim", () => {
    for (const parent of [
      `<div className="flex gap-3">`,
      `<div className="flex flex-row gap-3">`,
      `<div className="items-center gap-2">`,
    ]) {
      const { findings } = flex1InAColumn.run(
        file(`${parent}\n  <Button className="flex-1">Search</Button>\n</div>`),
      );

      expect(findings, parent).toEqual([]);
    }
  });

  it("accepts a responsive flex-1 against a base column — it is inert below sm", () => {
    // `sm:flex-1` wakes up when the row does; below sm the button keeps
    // its pinned height. The narrow rule says nothing about it.
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col sm:flex-row gap-3">
  <Button className="sm:flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not blame a column behind a wrapper the button is not a flex item of", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col sm:flex-row gap-3">
  <div>
    <Button className="flex-1">Save</Button>
  </div>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("gives up when the parent's className is built by cn()", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className={cn("flex", vertical && "flex-col")}>
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("reads tokens, not substrings — flex-initial is not flex-1", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col sm:flex-row gap-3">
  <Button className="flex-initial">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("asks for the display: a lone direction class makes no flex container", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex-col gap-3">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves flex-auto alone — its basis is auto, so the pinned height survives", () => {
    // Measured: a 44px button in a column with no height stays 44px.
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col gap-3">
  <Button className="flex-auto">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("reads grow over basis-0, in either order", () => {
    for (const fill of ["grow basis-0", "basis-0 grow", "basis-0"]) {
      const { findings } = flex1InAColumn.run(
        file(`<div className="flex flex-col gap-3">
  <Button className="${fill}">Save</Button>
</div>`),
      );

      expect(findings, fill).toEqual(["modules/things/ThingPage.tsx:2"]);
    }
  });

  it("reads a column written as a max-width variant", () => {
    // `flex max-sm:flex-col` is the phone column the rule already catches,
    // spelled from the other end of the breakpoint.
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex gap-3 max-sm:flex-col">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("flags a max-width column claimed on its own — it names the phone layout by construction", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="max-sm:flex-col">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("accepts a column that states its own height — the fill has a box", () => {
    for (const height of [
      "flex flex-col h-64",
      "flex flex-col min-h-64",
      "flex flex-col h-[50vh]",
    ]) {
      const { findings } = flex1InAColumn.run(
        file(`<div className="${height}">
  <Button className="flex-1">Save</Button>
</div>`),
      );

      expect(findings, height).toEqual([]);
    }
  });

  it("still flags min-h-0 — permission to shrink is not a height", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col min-h-0">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("accepts a definite height written for the narrow screen only", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col max-sm:h-64">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("blames basis-0 on its own — the zero basis is what drops the height (21px measured)", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col gap-3">
  <Button className="basis-0">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("does not blame grow alone — without the zero basis the height stays 44px", () => {
    const { findings } = flex1InAColumn.run(
      file(`<div className="flex flex-col gap-3">
  <Button className="grow">Save</Button>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("refuses heights that are not heights: zero, one pixel, intrinsic", () => {
    for (const height of [
      "h-0",
      "h-px",
      "h-[0px]",
      "h-[0vh]",
      "h-[0%]",
      "min-h-px",
      "min-h-[0px]",
      "h-min",
      "h-max",
      "h-auto",
      "h-fit",
    ]) {
      const { findings } = flex1InAColumn.run(
        file(`<div className="flex flex-col ${height}">
  <Button className="flex-1">Save</Button>
</div>`),
      );

      expect(findings, height).toEqual(["modules/things/ThingPage.tsx:2"]);
    }
  });

  it("still accepts real lengths that merely start like the refused ones", () => {
    for (const height of ["h-0.5", "h-10", "h-[10px]", "h-screen", "min-h-screen"]) {
      const { findings } = flex1InAColumn.run(
        file(`<div className="flex flex-col ${height}">
  <Button className="flex-1">Save</Button>
</div>`),
      );

      expect(findings, height).toEqual([]);
    }
  });

  it("survives a closing tag of an element it never saw open", () => {
    const { findings } = flex1InAColumn.run(
      file(`</section>
<div className="flex flex-col sm:flex-row gap-3">
  <Button className="flex-1">Save</Button>
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:3"]);
  });
});
