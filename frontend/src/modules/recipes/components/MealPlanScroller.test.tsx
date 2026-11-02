import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { MealPlanScroller } from "./MealPlanScroller";

const proto = HTMLElement.prototype;
const originals = {
  scrollWidth: Object.getOwnPropertyDescriptor(proto, "scrollWidth"),
  clientWidth: Object.getOwnPropertyDescriptor(proto, "clientWidth"),
};

function stubMetrics(scrollWidth: number, clientWidth: number) {
  Object.defineProperty(proto, "scrollWidth", {
    configurable: true,
    get: () => scrollWidth,
  });
  Object.defineProperty(proto, "clientWidth", {
    configurable: true,
    get: () => clientWidth,
  });
}

afterEach(() => {
  for (const key of ["scrollWidth", "clientWidth"] as const) {
    const original = originals[key];
    if (original) Object.defineProperty(proto, key, original);
    else delete (proto as unknown as Record<string, unknown>)[key];
  }
});

const fade = (container: HTMLElement) =>
  container.querySelector(".bg-gradient-to-l");

describe("MealPlanScroller", () => {
  it("draws no fade when the whole grid fits", () => {
    // The fade used to sit on the last column unconditionally, so a week that
    // fit at 1440px still had its right edge washed out.
    stubMetrics(1348, 1348);
    const { container } = render(
      <MealPlanScroller>
        <div>grid</div>
      </MealPlanScroller>,
    );
    expect(fade(container)).toBeNull();
  });

  it("draws the fade while there is more grid to the right", () => {
    stubMetrics(1400, 700);
    const { container } = render(
      <MealPlanScroller>
        <div>grid</div>
      </MealPlanScroller>,
    );
    expect(fade(container)).not.toBeNull();
  });

  it("takes the fade away once scrolled to the end", () => {
    stubMetrics(1400, 700);
    const { container } = render(
      <MealPlanScroller>
        <div>grid</div>
      </MealPlanScroller>,
    );
    const track = container.querySelector(".overflow-x-auto") as HTMLElement;
    track.scrollLeft = 700;
    fireEvent.scroll(track);
    expect(fade(container)).toBeNull();
  });
});
