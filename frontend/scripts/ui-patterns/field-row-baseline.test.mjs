import { describe, expect, it } from "vitest";
import fieldRowBaseline from "./field-row-baseline.mjs";

const file = (text) => [{ path: "modules/things/ThingForm.tsx", text }];

describe("field-row-baseline", () => {
  it("reports two labelled fields in a row that never says how they line up", () => {
    const { findings } = fieldRowBaseline.run(
      file(`<div className="grid grid-cols-2 gap-3">
  <Input label={t("width")} value={w} />
  <Input label={t("height")} value={h} />
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("accepts a row that has answered the question", () => {
    for (const alignment of ["items-end", "items-start", "sm:items-end"]) {
      const { findings } = fieldRowBaseline.run(
        file(`<div className="grid grid-cols-2 gap-3 ${alignment}">
  <Input label={t("width")} value={w} />
  <NativeSelect label={t("unit")} value={u} />
</div>`),
      );

      expect(findings, alignment).toEqual([]);
    }
  });

  it("leaves a row alone when only one of its children carries a label", () => {
    // One label cannot be taller than the other one.
    const { findings } = fieldRowBaseline.run(
      file(`<div className="grid grid-cols-2 gap-3">
  <Input label={t("width")} value={w} />
  <Input aria-label="height" value={h} />
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not blame a row for the fields inside a nested one", () => {
    const { findings } = fieldRowBaseline.run(
      file(`<div className="grid grid-cols-2 gap-6">
  <section>
    <div className="grid grid-cols-2 gap-3 items-end">
      <Input label={t("width")} value={w} />
      <Input label={t("height")} value={h} />
    </div>
  </section>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("says nothing about a single-column stack", () => {
    const { findings } = fieldRowBaseline.run(
      file(`<div className="grid grid-cols-1 gap-3">
  <Input label={t("width")} value={w} />
  <Input label={t("height")} value={h} />
</div>`),
    );

    expect(findings).toEqual([]);
  });
});
