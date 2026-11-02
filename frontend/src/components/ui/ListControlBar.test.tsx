import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ListControlBar } from "./ListControlBar";

describe("ListControlBar", () => {
  it("renders nothing when no props provided", () => {
    const { container } = render(<ListControlBar />);
    expect(container.firstChild).toBeNull();
  });

  describe("search", () => {
    it("renders search input with placeholder", () => {
      render(
        <ListControlBar
          search={{
            value: "",
            onChange: vi.fn(),
            placeholder: "Search items...",
          }}
        />,
      );
      expect(
        screen.getByPlaceholderText("Search items..."),
      ).toBeInTheDocument();
    });

    it("gives the search field an accessible name from its placeholder", () => {
      render(
        <ListControlBar
          search={{
            value: "",
            onChange: vi.fn(),
            placeholder: "Search by number, reference…",
          }}
        />,
      );
      expect(
        screen.getByLabelText("Search by number, reference…"),
      ).toBeInTheDocument();
    });

    it("falls back to a translated name when there is no placeholder", () => {
      render(<ListControlBar search={{ value: "", onChange: vi.fn() }} />);
      expect(screen.getByLabelText("Search")).toBeInTheDocument();
    });

    it("calls onChange when user types", () => {
      const onChange = vi.fn();
      render(
        <ListControlBar
          search={{ value: "", onChange, placeholder: "Search..." }}
        />,
      );
      fireEvent.change(screen.getByPlaceholderText("Search..."), {
        target: { value: "abc" },
      });
      expect(onChange).toHaveBeenCalledWith("abc");
    });

    it("shows clear button when search has value", () => {
      const onChange = vi.fn();
      render(<ListControlBar search={{ value: "hello", onChange }} />);
      const clearBtn = screen.getByLabelText("Clear search");
      expect(clearBtn).toBeInTheDocument();
      fireEvent.click(clearBtn);
      expect(onChange).toHaveBeenCalledWith("");
    });

    it("hides clear button when search is empty", () => {
      render(<ListControlBar search={{ value: "", onChange: vi.fn() }} />);
      expect(screen.queryByLabelText("Clear search")).not.toBeInTheDocument();
    });
  });

  describe("primaryTabs", () => {
    const tabs = {
      value: "all",
      onChange: vi.fn(),
      options: [
        { value: "all", label: "All" },
        { value: "active", label: "Active" },
        { value: "done", label: "Done" },
      ],
    };

    it("renders tab buttons", () => {
      render(<ListControlBar primaryTabs={tabs} />);
      expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Active" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Done" })).toBeInTheDocument();
    });

    it("calls onChange when tab clicked", async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      render(<ListControlBar primaryTabs={{ ...tabs, onChange }} />);
      await user.click(screen.getByRole("tab", { name: "Active" }));
      expect(onChange).toHaveBeenCalledWith("active");
    });
  });

  describe("secondaryFilters", () => {
    const filters = [
      { key: "expired", label: "Expired", active: false, onToggle: vi.fn() },
      { key: "low", label: "Low stock", active: true, onToggle: vi.fn() },
    ];

    it("renders filter chips", () => {
      render(<ListControlBar secondaryFilters={filters} />);
      expect(screen.getByText("Expired")).toBeInTheDocument();
      expect(screen.getByText("Low stock")).toBeInTheDocument();
    });

    it("calls onToggle when chip clicked", () => {
      const onToggle = vi.fn();
      render(
        <ListControlBar
          secondaryFilters={[
            { key: "expired", label: "Expired", active: false, onToggle },
          ]}
        />,
      );
      fireEvent.click(screen.getByText("Expired"));
      expect(onToggle).toHaveBeenCalled();
    });

    // Two unlabelled rows that both start with "All" read as one filter in two
    // states — the caption names what each row filters by, and the group gives
    // assistive technology the same information.
    it("names the chip row when a label is given", () => {
      render(
        <ListControlBar
          secondaryFilters={filters}
          secondaryFiltersLabel="Status"
        />,
      );
      expect(screen.getByRole("group", { name: "Status" })).toBeInTheDocument();
      expect(screen.getByText("Status")).toBeInTheDocument();
    });

    it("leaves the row unnamed when no label is given", () => {
      render(<ListControlBar secondaryFilters={filters} />);
      expect(screen.queryByRole("group")).not.toBeInTheDocument();
    });

    // The fill is the state for the eye; a screen reader needs it said. A
    // chip without aria-pressed reads the same on and off.
    it("states whether each chip is on", () => {
      render(<ListControlBar secondaryFilters={filters} />);
      expect(screen.getByRole("button", { name: "Expired" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
      expect(screen.getByRole("button", { name: "Low stock" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    it("carries chip state with a fill, not an outline", () => {
      render(<ListControlBar secondaryFilters={filters} />);
      const inactive = screen.getByTestId("filter-expired");
      const active = screen.getByTestId("filter-low");
      expect(inactive.className).toContain("bg-surface-raised");
      expect(inactive.className.split(/\s+/)).not.toContain("border");
      expect(active.className).toContain("ring-1");
      expect(active.className.split(/\s+/)).not.toContain("border");
    });
  });

  describe("viewToggle", () => {
    it("renders grid and list buttons", () => {
      render(
        <ListControlBar viewToggle={{ mode: "grid", onChange: vi.fn() }} />,
      );
      expect(screen.getByLabelText("Grid view")).toBeInTheDocument();
      expect(screen.getByLabelText("List view")).toBeInTheDocument();
    });

    it("calls onChange with correct mode", () => {
      const onChange = vi.fn();
      render(<ListControlBar viewToggle={{ mode: "grid", onChange }} />);
      fireEvent.click(screen.getByLabelText("List view"));
      expect(onChange).toHaveBeenCalledWith("list");
    });
  });

  describe("viewToggle beside scrolling tabs", () => {
    it("stays out of the tab strip's scroller, so a phone never clips it", () => {
      render(
        <ListControlBar
          primaryTabs={{
            value: "a",
            onChange: vi.fn(),
            options: [
              { value: "a", label: "All Statuses" },
              { value: "b", label: "Available" },
              { value: "c", label: "In use" },
              { value: "d", label: "Reserved" },
            ],
          }}
          viewToggle={{ mode: "list", onChange: vi.fn() }}
        />,
      );
      const toggle = screen.getByLabelText("Grid view");
      // The tab strip scrolls (overflow-x-auto); the toggle must not sit in it.
      expect(screen.getByRole("tablist").closest(".overflow-x-auto")).not.toBe(
        null,
      );
      expect(toggle.closest(".overflow-x-auto")).toBeNull();
    });
  });

  describe("filterButton", () => {
    it("renders filter button", () => {
      render(
        <ListControlBar filterButton={{ activeCount: 0, onClick: vi.fn() }} />,
      );
      expect(screen.getByText("Filter")).toBeInTheDocument();
    });

    it("shows active count badge when filters active", () => {
      render(
        <ListControlBar filterButton={{ activeCount: 3, onClick: vi.fn() }} />,
      );
      expect(screen.getByText("3")).toBeInTheDocument();
    });

    it("calls onClick when clicked", () => {
      const onClick = vi.fn();
      render(<ListControlBar filterButton={{ activeCount: 0, onClick }} />);
      fireEvent.click(screen.getByText("Filter"));
      expect(onClick).toHaveBeenCalled();
    });
  });

  describe("resultCount", () => {
    it("displays result count with default label", () => {
      render(
        <ListControlBar
          secondaryFilters={[
            { key: "a", label: "A", active: false, onToggle: vi.fn() },
          ]}
          resultCount={42}
        />,
      );
      expect(screen.getByText("42 results")).toBeInTheDocument();
    });

    it("displays result count with custom label", () => {
      render(
        <ListControlBar
          secondaryFilters={[
            { key: "a", label: "A", active: false, onToggle: vi.fn() },
          ]}
          resultCount={7}
          resultCountLabel="items found"
        />,
      );
      expect(screen.getByText("7 items found")).toBeInTheDocument();
    });

    it("says more than the count where the list stopped counting", () => {
      render(
        <ListControlBar
          secondaryFilters={[
            { key: "a", label: "A", active: false, onToggle: vi.fn() },
          ]}
          resultCount={10000}
          resultCountLabel="movements"
          resultCountCapped
        />,
      );
      expect(screen.getByText("more than 10000 movements")).toBeInTheDocument();
    });

    /**
     * the count shared a wrapping row with the chips, so a fourth chip
     * (one extra installed module) pushed both onto a second band and the list
     * down with them. The chips scroll now, and the count sits outside their
     * track.
     */
    it("keeps the count out of the chip track, however many chips there are", () => {
      render(
        <ListControlBar
          secondaryFilters={Array.from({ length: 6 }, (_, i) => ({
            key: `f${i}`,
            label: `Filter number ${i}`,
            active: false,
            onToggle: vi.fn(),
          }))}
          resultCount={42}
        />,
      );

      const count = screen.getByText("42 results");
      const track = screen.getByTestId("filter-f0")
        .parentElement as HTMLElement;

      // Same band: the count is the track's sibling, not a row of its own…
      expect(track.contains(count)).toBe(false);
      expect(count.parentElement).toBe(track.parentElement);

      // …and from `sm:` up the track scrolls instead of wrapping, so its
      // height does not grow with the chip count.
      const tokens = track.className.split(/\s+/);
      expect(tokens).toContain("overflow-x-auto");
      expect(tokens).not.toContain("flex-wrap");
      expect(count.className).toContain("shrink-0");
    });

    it("gives the count its own band above a single scrolling chip row on a phone", () => {
      render(
        <ListControlBar
          secondaryFilters={Array.from({ length: 6 }, (_, i) => ({
            key: `f${i}`,
            label: `Filter number ${i}`,
            active: false,
            onToggle: vi.fn(),
          }))}
          resultCount={580}
          resultCountLabel="records"
        />,
      );

      const count = screen.getByText("580 records");
      const track = screen.getByTestId("filter-f0")
        .parentElement as HTMLElement;
      const row = track.parentElement as HTMLElement;

      // Stacked column below `sm:`, the count ahead of the chips…
      expect(row.className.split(/\s+/)).toContain("flex-col");
      expect(row.className.split(/\s+/)).toContain("sm:flex-row");
      expect(count.className.split(/\s+/)).toContain("order-first");
      // …and the chips do not wrap: seven of them took three rows and pushed
      // the first record of the list below a phone's fold. The track scrolls
      // and fades at its edge instead.
      expect(track.className.split(/\s+/)).not.toContain("flex-wrap");
      expect(track.className.split(/\s+/)).toContain("overflow-x-auto");
    });
  });

  it("renders full control bar with all props", () => {
    render(
      <ListControlBar
        search={{ value: "", onChange: vi.fn(), placeholder: "Search..." }}
        primaryTabs={{
          value: "all",
          onChange: vi.fn(),
          options: [
            { value: "all", label: "All" },
            { value: "active", label: "Active" },
          ],
        }}
        secondaryFilters={[
          {
            key: "expired",
            label: "Expired",
            active: false,
            onToggle: vi.fn(),
          },
        ]}
        viewToggle={{ mode: "list", onChange: vi.fn() }}
        resultCount={10}
      />,
    );
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getByLabelText("Grid view")).toBeInTheDocument();
    expect(screen.getByText("10 results")).toBeInTheDocument();
  });

  describe("primary action", () => {
    /**
     * The action stands outside the tabs' scroll track, and the search
     * field's flex-1 eats the row's slack — so above `sm` the action lands
     * at the row's right end, and below it the row stacks with the action
     * on its own band. Inside the track it could be carried out of reach
     * by a long tab list.
     */
    it("keeps the action at the right end of its row", () => {
      render(
        <ListControlBar
          search={{ value: "", onChange: vi.fn(), placeholder: "Search..." }}
          primaryAction={<button type="button">Add</button>}
        />,
      );

      const group = screen.getByRole("button", { name: "Add" }).parentElement!;
      // Its own band in the stacked row, last in the band — not buried at a
      // scroll offset inside the tab track.
      expect(group.parentElement!.lastElementChild).toBe(group);
    });

    it("adds no group when there is no action", () => {
      const { container } = render(
        <ListControlBar
          search={{ value: "", onChange: vi.fn(), placeholder: "Search..." }}
        />,
      );

      expect(container.querySelector(".ml-auto")).toBeNull();
    });

    /**
     * The bar lives under the root's overflow-x-hidden: a row that cannot
     * wrap, ending in a don't-shrink action group, grows past a phone and
     * is cut off unreachable — "Export CSV" was measured ending at 489px
     * in a 320px viewport on /recipes/ingredient-data (546px in DE). The
     * group must fall to a band of its own and fold its buttons there.
     */
    it("wraps its buttons instead of running past the viewport", () => {
      render(
        <ListControlBar
          search={{ value: "", onChange: vi.fn(), placeholder: "Search..." }}
          primaryAction={
            <>
              <button type="button">Add ingredient</button>
              <button type="button">Import</button>
              <button type="button">Export CSV</button>
            </>
          }
        />,
      );

      const group = screen.getByRole("button", {
        name: "Add ingredient",
      }).parentElement!;
      // Alone on its band the group may shrink to the row's width — and
      // wrap its buttons inside instead of pushing them past the clip.
      expect(group.className).toContain("flex-wrap");
      expect(group.className).toContain("min-w-0");
      expect(group.className).not.toContain("shrink-0");
      // The row around the track wraps too, so an overfull action group
      // leaves the tabs' line instead of being laid out beyond the
      // viewport next to them.
      expect(group.parentElement!.className).toContain("flex-wrap");
    });
  });

  describe("an overlong tab row", () => {
    const fortyTabs = {
      value: "all",
      onChange: vi.fn(),
      options: Array.from({ length: 40 }, (_, i) => ({
        value: `tab-${i}`,
        label: `Tab ${i}`,
      })),
    };

    it("scrolls its tabs instead of widening the page", () => {
      render(
        <ListControlBar
          primaryTabs={fortyTabs}
          primaryAction={<button>Add</button>}
        />,
      );

      // The scrolling track must be allowed to be narrower than its content:
      // `shrink-0` forbade that (the row widened the page) and `flex-wrap`
      // wrapped what should have scrolled. The tab strip has a scroller of
      // its own inside — the invariant belongs to the bar's track around it.
      const track = screen.getByRole("tablist").closest('[class*="min-w-0"]')!;
      expect(track.className).toContain("min-w-0");
      expect(track.className).toContain("overflow-x-auto");
      expect(track.className).not.toContain("shrink-0");
      expect(track.className).not.toContain("flex-wrap");
    });

    it("keeps the primary action outside the scroll track", () => {
      render(
        <ListControlBar
          primaryTabs={fortyTabs}
          primaryAction={<button>Add</button>}
        />,
      );

      const action = screen.getByRole("button", { name: "Add" });
      const track = screen.getByRole("tablist").closest(".overflow-x-auto")!;
      // A scroller can carry its children out of reach; the primary action
      // must not live in one.
      expect(track.contains(action)).toBe(false);
      // And it cannot be crushed by the tabs either: sharing a line with
      // the track only happens when both fit, because both wrap.
      expect(action.parentElement!.className).toContain("flex-wrap");
      expect(action.parentElement!.className).toContain("min-w-0");
    });

    it("gives the search field a width floor on desktop", () => {
      render(
        <ListControlBar
          search={{ value: "", onChange: vi.fn() }}
          primaryTabs={fortyTabs}
        />,
      );

      // `flex-1` alone had a 0% basis: in an overfull row the field collapsed
      // to a square around its icon. The floor holds the input at ~14 rem.
      const wrapper = screen
        .getByTestId("list-search-input")
        .closest("div.relative")!.parentElement!;
      expect(wrapper.className).toContain("sm:min-w-56");
      expect(wrapper.className).toContain("sm:basis-56");
    });

    it("stacks the row on phones, where full width beats any floor", () => {
      const { container } = render(
        <ListControlBar
          search={{ value: "", onChange: vi.fn() }}
          primaryTabs={fortyTabs}
        />,
      );

      const row = container
        .querySelector('[data-testid="list-search-input"]')!
        .closest(".flex-col");
      expect(row).not.toBeNull();
    });
  });
});
