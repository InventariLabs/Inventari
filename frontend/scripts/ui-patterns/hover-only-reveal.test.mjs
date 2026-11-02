import { describe, expect, it } from "vitest";
import hoverOnlyReveal from "./hover-only-reveal.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("hover-only-reveal", () => {
  it("reports the shape that hid 'Remove member'", () => {
    const { findings } = hoverOnlyReveal.run(
      files(
        `<Button className="text-on-muted opacity-0 group-hover:opacity-100 transition-all" />`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("reports a named group the same way", () => {
    const { findings } = hoverOnlyReveal.run(
      files(`<Button className="opacity-0 group-hover/name:opacity-100" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("accepts the guarded pattern the recipe card uses", () => {
    const { findings } = hoverOnlyReveal.run(
      files(
        `<div className="transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("is not satisfied by a focus reveal that still hides on a phone", () => {
    // Above the breakpoint the keyboard can reach it; a finger still cannot.
    const { findings } = hoverOnlyReveal.run(
      files(
        `<div className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100" />`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("is not satisfied by a breakpoint alone", () => {
    const { findings } = hoverOnlyReveal.run(
      files(`<div className="md:opacity-0 md:group-hover:opacity-100" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("leaves a tooltip alone — nothing focuses or taps it", () => {
    const { findings } = hoverOnlyReveal.run(
      files(
        `<div className="absolute opacity-0 group-hover:opacity-100 pointer-events-none" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("does not let a sibling's guard cover an unguarded tag", () => {
    const { findings } = hoverOnlyReveal.run(
      files(`<div className="md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100" />
<span className="opacity-0 group-hover:opacity-100" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });

  it("ignores a state-driven reveal with no hover in it", () => {
    const { findings } = hoverOnlyReveal.run(
      files(`<div className={swipeX > 50 ? "opacity-100" : "opacity-0"} />`),
    );

    expect(findings).toEqual([]);
  });
});
