import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TagFilterChips } from "./TagFilterChips";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";

function tags(count: number): RecipeTagItem[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `tag-${i + 1}`,
    count: i + 1,
    color: null,
  }));
}

const baseProps = {
  selectedTags: [] as string[],
  onToggleTag: vi.fn(),
  onClearTags: vi.fn(),
  clearTagsText: "Clear tags",
  showMoreText: "Show all tags",
  showLessText: "Show less",
};

describe("TagFilterChips active state", () => {
  it("carries the selected state on the canonical pill, not on a ramp step", () => {
    render(
      <TagFilterChips
        {...baseProps}
        allTags={tags(2)}
        selectedTags={["tag-1"]}
      />,
    );
    const chip = screen.getByRole("button", { name: /tag-1/ });

    // A profile theme may repaint the whole primary ramp (ADR-013), so a label
    // painted with a ramp step has a contrast nobody controls. The neutral
    // `text-on` is high-contrast in both themes by construction.
    expect(chip.className).toContain("bg-primary-50");
    expect(chip.className).toContain("border-primary-500");
    expect(chip.className).toContain("text-on");
    // Weight is no longer one of the signals: a 12px chip does not carry a
    // title weight (§1.2), and the base pill is already `font-medium`, so
    // repeating it said nothing about being selected. Colour and border do.
    expect(chip.className).not.toContain("font-semibold");
    expect(chip.className).not.toContain("text-primary-700");
    expect(chip.className).not.toContain("dark:");
  });
});

describe("TagFilterChips tag limit", () => {
  it("collapses long tag lists behind a show-more toggle", () => {
    render(<TagFilterChips {...baseProps} allTags={tags(12)} />);

    // 8 visible chips, toggle offers the remaining 4.
    expect(screen.getByText("tag-1")).toBeInTheDocument();
    expect(screen.getByText("tag-8")).toBeInTheDocument();
    expect(screen.queryByText("tag-9")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /show all tags/i });

    fireEvent.click(toggle);
    expect(screen.getByText("tag-12")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show less/i }),
    ).toBeInTheDocument();
  });

  it("keeps a selected tag visible even beyond the collapsed limit", () => {
    render(
      <TagFilterChips
        {...baseProps}
        allTags={tags(12)}
        selectedTags={["tag-10"]}
      />,
    );
    expect(screen.getByText("tag-10")).toBeInTheDocument();
    expect(screen.queryByText("tag-9")).not.toBeInTheDocument();
  });

  it("renders all chips when the list is within the limit", () => {
    render(<TagFilterChips {...baseProps} allTags={tags(4)} />);
    expect(screen.getByText("tag-4")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show all tags/i }),
    ).not.toBeInTheDocument();
  });
});
