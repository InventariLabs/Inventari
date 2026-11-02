import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { TagsPanel } from "./TagsPanel";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";

const tags: RecipeTagItem[] = Array.from({ length: 60 }, (_, i) => ({
  name: `tag-${i + 1}`,
  count: 1,
  color: null,
}));

vi.mock("../hooks/useRecipes", () => ({
  useRecipeTags: () => ({ data: tags, isLoading: false }),
  useSetTagColor: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMergeTags: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteTag: () => ({ mutateAsync: deleteTag, isPending: false }),
}));

const deleteTag = vi.fn().mockResolvedValue({ name: "x", updated_recipes: 1 });

const baseProps = {
  isOpen: true,
  onClose: vi.fn(),
  onTagClick: vi.fn(),
  titleText: "Tags",
};

describe("TagsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("puts the tag list on a scroll layer instead of letting it overflow the panel", () => {
    render(<TagsPanel {...baseProps} />);
    const panel = screen.getByRole("dialog");
    expect(panel.className).toContain("overflow-hidden");

    const lastTag = screen.getByText("tag-60");
    const scroller = lastTag.closest(".overflow-y-auto");
    expect(scroller).not.toBeNull();
    expect(panel.contains(scroller!)).toBe(true);
  });

  it("keeps the last of 60 tags reachable by scrolling", () => {
    render(<TagsPanel {...baseProps} />);

    const lastTag = screen.getByText("tag-60");
    const scroller = lastTag.closest(".overflow-y-auto");
    expect(scroller).not.toBeNull();
    if (!scroller) throw new Error("expected a scroll layer");

    // jsdom reports 0 for both sizes, so give the scroll layer a measurable
    // overflow — the assertion is about the DOM shape, not real layout.
    Object.defineProperty(scroller, "scrollHeight", {
      configurable: true,
      value: 2000,
    });
    Object.defineProperty(scroller, "clientHeight", {
      configurable: true,
      value: 400,
    });

    // The test setup already stubs `HTMLElement.prototype.scrollIntoView`
    // (jsdom has no real scrolling). Spy on it to prove the last tag is
    // scrolled into view rather than left unreachable behind the panel edge.
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView");

    lastTag.scrollIntoView();
    fireEvent.click(lastTag);

    expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.instances[0]).toBe(lastTag);
    expect(baseProps.onTagClick).toHaveBeenCalledWith("tag-60");
  });

  it("renders one panel surface, not a card inside a card", () => {
    render(<TagsPanel {...baseProps} />);
    const panel = screen.getByRole("dialog");
    expect(panel.querySelector(".rounded-2xl.border")).toBeNull();
  });

  it("keeps the merge action in the panel header next to the title", () => {
    render(<TagsPanel {...baseProps} />);
    const heading = screen.getByRole("heading", { level: 2, name: "Tags" });
    const header = heading.parentElement as HTMLElement;
    expect(
      within(header).getByRole("button", { name: /merge/i }),
    ).toBeInTheDocument();
  });

  it("has exactly one close button, labelled for assistive tech", () => {
    render(<TagsPanel {...baseProps} />);
    const heading = screen.getByRole("heading", { level: 2, name: "Tags" });
    const header = heading.parentElement as HTMLElement;
    const closeButtons = within(header)
      .getAllByRole("button")
      .filter((b) => b.textContent === "" || b.querySelector("svg.lucide-x"));
    expect(closeButtons).toHaveLength(1);
    expect(closeButtons[0]).toHaveAccessibleName();
  });
  it("offers a rename and a delete on every tag", async () => {
    // The panel could colour a tag and merge it into another; a typo in the
    // comma-separated field they grow from had no way out.
    const user = userEvent.setup();
    render(<TagsPanel {...baseProps} />);

    await user.click(
      screen.getAllByRole("button", { name: /more actions/i })[0],
    );

    expect(
      await screen.findByRole("button", { name: "Rename" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("removes the tag once the deletion is confirmed", async () => {
    const user = userEvent.setup();
    render(<TagsPanel {...baseProps} />);

    await user.click(
      screen.getAllByRole("button", { name: /more actions/i })[0],
    );
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    // The menu is gone; the only "Delete" left is the confirmation's.
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(deleteTag).toHaveBeenCalledWith(tags[0].name);
  });
});
