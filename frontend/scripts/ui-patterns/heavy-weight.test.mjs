import { describe, expect, it } from "vitest";
import heavyweight from "./heavy-weight.mjs";

const file = (text) => [{ path: "modules/things/ThingForm.tsx", text }];

describe("heavy-weight", () => {
  it("reports font-bold in a class that also asks for uppercase", () => {
    const { findings } = heavyweight.run(
      file(`<span className="text-[10px] font-mono font-bold uppercase tracking-tight">A-01</span>`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("reports font-bold on a heading element", () => {
    const { findings } = heavyweight.run(
      file(`<h3 className="font-mono font-bold text-lg">WH-01</h3>`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("reports font-bold beside text-xs", () => {
    const { findings } = heavyweight.run(
      file(`<span className="block text-xs font-mono font-bold text-on-secondary">SKU-1</span>`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("says nothing about a heavy weight with none of the three shapes", () => {
    // A big mono code or a numeric tile: the seven is the content of the box.
    const { findings } = heavyweight.run(
      file(`<p className="font-mono text-2xl font-bold text-on mb-2">WH-01</p>`),
    );

    expect(findings).toEqual([]);
  });

  it("accepts the drained label weights", () => {
    for (const className of [
      "text-[10px] font-medium uppercase tracking-widest",
      "text-xs font-medium uppercase text-on-muted",
      "font-mono font-semibold text-lg text-on",
    ]) {
      const { findings } = heavyweight.run(
        file(`<span className="${className}">Label</span>`),
      );

      expect(findings, className).toEqual([]);
    }
  });

  it("reads a font-bold inside a cn expression", () => {
    const { findings } = heavyweight.run(
      file("<div className={cn(\"text-xs font-bold\", active && \"text-on\")}>x</div>"),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("excuses a site whose marker carries a sentence", () => {
    const { findings } = heavyweight.run(
      file(`{/* ui-pattern: heavy-weight — the SKU and barcode are codes and the monospace bold is the code treatment the typography table keeps */}
<span className="text-xs font-mono font-bold">SKU-1</span>`),
    );

    expect(findings).toEqual([]);
  });

  it("refuses an excuse whose reason is not a sentence", () => {
    const { findings } = heavyweight.run(
      file(`{/* ui-pattern: heavy-weight — looks nice */}
<span className="text-xs font-mono font-bold">SKU-1</span>`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:2"]);
  });

  it("reads a reason continued on the next line", () => {
    const { findings } = heavyweight.run(
      file(`{/* ui-pattern: heavy-weight — the figure alone
    is the content of this cell and the weight keeps it readable */}
<span className="text-xs font-mono font-bold">42</span>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read a bold example in a doc comment as code", () => {
    const { findings } = heavyweight.run(
      file(`/**
 *   <span className="text-xs font-bold">example</span>
 */
const x = 1;`),
    );

    expect(findings).toEqual([]);
  });
});
