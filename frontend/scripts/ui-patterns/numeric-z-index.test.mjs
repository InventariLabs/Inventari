import { describe, expect, it } from "vitest";
import numericZIndex from "./numeric-z-index.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("numeric-z-index", () => {
  it("reports an arbitrary numeric class and a numeric style value", () => {
    const { findings } = numericZIndex.run(
      files(`<div className="fixed inset-0 z-[100]" />
      const style = { zIndex: isDragging ? 30 : undefined };
      const other = { zIndex: 10 };`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:2", "Fixture.tsx:3"]);
  });

  it("leaves the layer tokens and a conditional on a token alone", () => {
    const { findings } = numericZIndex.run(
      files(`<div className="z-[var(--z-modal)] z-10" />
      <Sheet zIndex="modal-nested" />
      <div style={{ zIndex: "var(--z-popover)" }} />
      const style = { zIndex: isDragging ? "var(--z-sticky)" : undefined };`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read a comment as the mistake", () => {
    const { findings } = numericZIndex.run(
      files(`/** A hand-rolled z-[100] backdrop was the old shape. */
      // zIndex: 50 used to live here
      <div className="z-[var(--z-modal)]" />`),
    );

    expect(findings).toEqual([]);
  });
});
