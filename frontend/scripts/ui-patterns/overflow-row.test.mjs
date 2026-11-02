import { describe, expect, it } from "vitest";
import overflowRow from "./overflow-row.mjs";

const file = (text, path = "modules/things/ThingPage.tsx") => [{ path, text }];

describe("overflow-row", () => {
  it("flags a TabsList that opts out of scrolling with nothing around it", () => {
    const { considered, findings } = overflowRow.run(
      file(`<Tabs>
  <TabsList scrollable={false}>
    <TabsTrigger value="a">A</TabsTrigger>
  </TabsList>
</Tabs>`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("accepts a TabsList that keeps the default (scrolls itself)", () => {
    const { considered, findings } = overflowRow.run(
      file(`<TabsList className="w-full">
  <TabsTrigger value="a">A</TabsTrigger>
</TabsList>`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual([]);
  });

  it("accepts an opted-out TabsList whose own className scrolls", () => {
    const { findings } = overflowRow.run(
      file(
        `<TabsList scrollable={false} className="overflow-x-auto">x</TabsList>`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("accepts an opted-out TabsList inside a ScrollRow opened before it", () => {
    const { findings } = overflowRow.run(
      file(`<ScrollRow>
  <Button>Filter</Button>
  <TabsList scrollable={false}>x</TabsList>
</ScrollRow>`),
    );

    expect(findings).toEqual([]);
  });

  it("accepts a wrapper with overflow-auto in the lookbehind window", () => {
    const { findings } = overflowRow.run(
      file(`<div className="overflow-auto">
  <TabsList scrollable={false}>x</TabsList>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("looks back far enough for a long correct preamble but not forever", () => {
    const filler = (n) => "x".repeat(n);
    const near = `<ScrollRow>${filler(500)}<TabsList scrollable={false}>x</TabsList>`;
    const far = `<ScrollRow>${filler(1200)}<TabsList scrollable={false}>x</TabsList>`;

    expect(overflowRow.run(file(near)).findings).toEqual([]);
    expect(overflowRow.run(file(far)).findings).toEqual([
      "modules/things/ThingPage.tsx:1",
    ]);
  });

  it("reports each offending TabsList on its own line", () => {
    const { findings } = overflowRow.run(
      file(`<TabsList scrollable={false}>a</TabsList>
<TabsList>b</TabsList>
<TabsList scrollable={false}>c</TabsList>`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:1",
      "modules/things/ThingPage.tsx:3",
    ]);
  });

  it("does not consider files without a TabsList", () => {
    const { considered, findings } = overflowRow.run(
      file(`<div scrollable={false} />`),
    );

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });
});
