import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, it, expect } from "vitest";
import { ScrollRow } from "@/components/ui/ScrollRow";

/**
 * jsdom reports zero for every layout measurement, so the tests below that
 * look at the scrollbar and the caller's role and name need no layout. The
 * edge fade does: its describe block further down gives the track a width and
 * a scroll position by hand.
 */
describe("ScrollRow", () => {
  it("hides the native scrollbar in every engine", () => {
    const { container } = render(<ScrollRow>chips</ScrollRow>);
    const track = container.firstElementChild as HTMLElement;

    expect(track.className).toContain("overflow-x-auto");
    expect(track.className).toContain("[scrollbar-width:none]");
    expect(track.className).toContain("[-ms-overflow-style:none]");
    expect(track.className).toContain("[&::-webkit-scrollbar]:hidden");
  });

  it("pads the track vertically, compensated by a negative margin", () => {
    // `overflow-x: auto` makes the vertical axis clip too, and a track exactly
    // as tall as its children cuts off whatever they paint outside their
    // border-box — the top and bottom of an active chip's `ring-*` and of any
    // keyboard focus `outline`. The padding makes room for that paint; the
    // negative margin keeps the layout unchanged. If this regresses, the clip
    // comes back for every ScrollRow caller at once.
    const { container } = render(<ScrollRow>chips</ScrollRow>);
    const track = container.firstElementChild as HTMLElement;

    expect(track.className).toContain("py-1");
    expect(track.className).toContain("-my-1");
  });

  it("keeps the caller's role, name and layout classes", () => {
    render(
      <ScrollRow role="group" aria-label="Status" className="flex gap-2">
        <button type="button">Draft</button>
      </ScrollRow>,
    );

    const group = screen.getByRole("group", { name: "Status" });
    expect(group.className).toContain("flex gap-2");
    // The children stay in the tab order; the track adds no stop of its own.
    expect(group).not.toHaveAttribute("tabindex");
    expect(screen.getByRole("button", { name: "Draft" })).toBeInTheDocument();
  });
});

/**
 * A clipping track shaves whatever its children paint outside their border
 * box, on every side it clips — not just the two the first fix covered.
 * The first chip in every filter row had its left edge cut against the scroll
 * container, reported from use as "the border is clipped on the left".
 */
describe("ScrollRow — paint room on all four sides", () => {
  it("pads horizontally as well as vertically, and takes the padding back out", () => {
    const { container } = render(
      <ScrollRow>
        <button>first</button>
      </ScrollRow>,
    );

    const track = container.firstElementChild as HTMLElement;
    expect(track.className).toContain("px-1");
    expect(track.className).toContain("-mx-1");
    // The vertical half, which was already there and must stay.
    expect(track.className).toContain("py-1");
    expect(track.className).toContain("-my-1");
  });
});

/**
 * The fade at an edge says "there is more this way". jsdom lays nothing out,
 * so the three measurements the row reads are given here; the fade is then
 * read back from the mask the row writes on its track.
 */
describe("ScrollRow — the fade at an edge that still has content behind it", () => {
  const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
  const saved = new Map<string, PropertyDescriptor | undefined>();

  function stubLayout(clientWidth: number, scrollWidth: number) {
    for (const [name, value] of [
      ["clientWidth", clientWidth],
      ["scrollWidth", scrollWidth],
    ] as const) {
      saved.set(name, Object.getOwnPropertyDescriptor(proto, name));
      Object.defineProperty(proto, name, { configurable: true, value });
    }
  }

  function scrollTo(track: HTMLElement, scrollLeft: number) {
    Object.defineProperty(track, "scrollLeft", {
      configurable: true,
      value: scrollLeft,
    });
    act(() => {
      fireEvent.scroll(track);
    });
  }

  const maskOf = (track: HTMLElement) => track.style.maskImage;

  afterEach(() => {
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(proto, name, descriptor);
      else delete proto[name];
    }
    saved.clear();
  });

  it("fades the right edge when the content overflows, and the left only after scrolling", () => {
    stubLayout(300, 900);
    const { container } = render(<ScrollRow>chips</ScrollRow>);
    const track = container.firstElementChild as HTMLElement;

    // At the start: content behind the right edge only.
    expect(maskOf(track)).toContain("#000 0,");
    expect(maskOf(track)).toContain("transparent 100%");

    // In the middle: both edges have content behind them.
    scrollTo(track, 300);
    expect(maskOf(track)).toContain("transparent 0, #000 1.5rem");
    expect(maskOf(track)).toContain("transparent 100%");
  });

  it("drops the right fade and keeps the left one once the track is scrolled to its end", () => {
    stubLayout(300, 900);
    const { container } = render(<ScrollRow>chips</ScrollRow>);
    const track = container.firstElementChild as HTMLElement;

    scrollTo(track, 600);

    expect(maskOf(track)).toContain("transparent 0, #000 1.5rem");
    expect(maskOf(track)).not.toContain("transparent 100%");
    expect(maskOf(track)).toContain("#000 100%");
  });

  it("puts no mask on a row whose content fits, at the start or after a scroll event", () => {
    stubLayout(300, 300);
    const { container } = render(<ScrollRow>chips</ScrollRow>);
    const track = container.firstElementChild as HTMLElement;

    expect(maskOf(track)).toBe("");

    scrollTo(track, 0);
    expect(maskOf(track)).toBe("");
  });
});
