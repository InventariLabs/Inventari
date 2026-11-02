import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ScrollRow } from "@/components/ui/ScrollRow";

/**
 * jsdom reports zero for every layout measurement, so the fade itself is not
 * observable here — what is observable is that the row never falls back to the
 * browser scrollbar, and that it keeps whatever role and name the caller gave
 * it. The fade is exercised by the responsive E2E probes.
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
