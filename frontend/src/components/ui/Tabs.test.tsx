import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Tabs, TabsContent, TabsList, TabsPanels, TabsTrigger } from "./Tabs";

const bar = (props?: {
  scrollable?: boolean;
  className?: string;
  size?: "sm" | "default";
}) => {
  const { size, ...list } = props ?? {};
  return (
    <Tabs defaultValue="a">
      <TabsList {...list} aria-label="Sections">
        <TabsTrigger value="a" size={size}>
          First
        </TabsTrigger>
        <TabsTrigger value="b" size={size}>
          Second
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
};

describe("TabsList", () => {
  it("scrolls its own tabs by default", () => {
    render(bar());
    const list = screen.getByRole("tablist");

    expect(list.className).toContain("overflow-x-auto");
    expect(list.className).toContain("max-w-full");
  });

  /**
   * A plain `justify-center` in a scroll container puts the first tab at a
   * negative scroll offset, where no gesture reaches it — the row centres
   * until it overflows, then it starts.
   */
  it("centres the tabs only while they fit", () => {
    render(bar());

    expect(screen.getByRole("tablist").className).toContain(
      "[justify-content:safe_center]",
    );
  });

  it("hides the scrollbar it scrolls with", () => {
    render(bar());
    const list = screen.getByRole("tablist");

    expect(list.className).toContain("[scrollbar-width:none]");
    expect(list.className).toContain("[&::-webkit-scrollbar]:hidden");
  });

  it("lets a caller opt out", () => {
    render(bar({ scrollable: false }));

    expect(screen.getByRole("tablist").className).not.toContain(
      "overflow-x-auto",
    );
  });

  it("merges a caller className", () => {
    render(bar({ className: "w-full" }));

    expect(screen.getByRole("tablist").className).toContain("w-full");
  });

  /**
   * jsdom has no layout, so the height cannot be measured here — what is
   * pinned is the rule that produced it. A fixed 40px bar leaves 28px between
   * its paddings, which is a `size="sm"` tab exactly and 12px short of a
   * default one; the oversized tab then filled the padding it should have sat
   * inside, and the active tab's ring, drawn just outside its box, was clipped
   * by the scrollport. Only the sides of it survived.
   */
  it("takes its height from the tabs rather than pinning one", () => {
    render(bar());

    expect(screen.getByRole("tablist").className).toContain("h-auto");
    expect(screen.getByRole("tablist").className).not.toContain("h-10");
  });

  it("keeps the ring that marks the active tab", () => {
    render(bar());

    // The clipping was the bug, not the ring — it still has to be asked for.
    expect(screen.getByRole("tab", { name: "First" }).className).toContain(
      "data-[state=active]:ring-1",
    );
  });
});

describe("TabsTrigger", () => {
  /**
   * At 320px three tabs with long labels overflow their buttons: the text
   * bleeds into the next tab because `whitespace-nowrap` prevents wrapping
   * and nothing clips the overflow. The result is unreadable overlapping
   * letters ("Domyślne składnPki" for "Domyślne składniki" + "Przelicznik").
   * Each tab must clip its own text to its own surface.
   */
  it("clips overflowing text to the tab's own surface", () => {
    render(bar());

    const trigger = screen.getByRole("tab", { name: "First" });
    expect(trigger.className).toContain("overflow-hidden");
  });

  /**
   * `flex-1` stretched every tab to fill the row equally, so long labels
   * overflowed their buttons and overlapped instead of letting the bar
   * scroll. `flex-none` lets each tab take its natural width so the
   * TabsList's `overflow-x-auto` can scroll when they exceed the viewport.
   */
  it("takes natural width so the bar can scroll past it", () => {
    render(bar());

    const trigger = screen.getByRole("tab", { name: "First" });
    expect(trigger.className).toContain("flex-none");
    expect(trigger.className).not.toContain("flex-1");
  });
});

/**
 * Two import sheets changed height with every tab — 48px and 120px, centred,
 * so the whole sheet jumped. A stacked panel shares one grid cell with its
 * siblings, which makes the cell as tall as the tallest of them.
 */
describe("TabsContent stacked", () => {
  const stacked = () => (
    <Tabs defaultValue="a">
      <TabsList aria-label="Sections">
        <TabsTrigger value="a">First</TabsTrigger>
        <TabsTrigger value="b">Second</TabsTrigger>
      </TabsList>
      <TabsPanels data-testid="panels">
        <TabsContent value="a" stacked>
          <p>short panel</p>
        </TabsContent>
        <TabsContent value="b" stacked>
          <p>tall panel</p>
        </TabsContent>
      </TabsPanels>
    </Tabs>
  );

  it("puts every panel in the same grid cell", () => {
    render(stacked());

    expect(screen.getByTestId("panels").className).toContain("grid");
    for (const panel of screen.getAllByRole("tabpanel", { hidden: true })) {
      expect(panel.className).toContain("col-start-1");
      expect(panel.className).toContain("row-start-1");
    }
  });

  it("keeps the hidden panel in the layout but not on the screen", () => {
    render(stacked());

    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    const inactive = panels.find((p) => p.dataset.state === "inactive");
    expect(inactive).toBeDefined();
    // `block` outranks the `hidden` attribute, so the panel still counts
    // towards the height; `invisible` is what hides it.
    expect(inactive?.className).toContain("data-[state=inactive]:block");
    expect(inactive?.className).toContain("data-[state=inactive]:invisible");
  });

  it("keeps every panel mounted so the cell can size to the tallest", () => {
    render(stacked());

    expect(screen.getByText("short panel")).toBeInTheDocument();
    expect(screen.getByText("tall panel")).toBeInTheDocument();
  });

  it("leaves an ordinary panel to unmount when it is not selected", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList aria-label="Sections">
          <TabsTrigger value="a">First</TabsTrigger>
          <TabsTrigger value="b">Second</TabsTrigger>
        </TabsList>
        <TabsContent value="a">
          <p>one</p>
        </TabsContent>
        <TabsContent value="b">
          <p>two</p>
        </TabsContent>
      </Tabs>,
    );

    expect(screen.getByText("one")).toBeInTheDocument();
    expect(screen.queryByText("two")).toBeNull();
  });
});

/**
 * A tab names the panel it controls, and Radix fills `aria-controls` in on
 * every trigger. A bar that only filters or switches something outside its
 * root mounts no panel, so the selected tab pointed at an id nothing on the
 * page carries — an invalid reference axe reports as critical.
 */
describe("Tabs without panels", () => {
  it("names the panel a tab controls when the panels exist", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList aria-label="Sections">
          <TabsTrigger value="a">First</TabsTrigger>
        </TabsList>
        <TabsContent value="a">Panel</TabsContent>
      </Tabs>,
    );

    const controls = screen
      .getByRole("tab", { name: "First" })
      .getAttribute("aria-controls");
    expect(document.getElementById(controls!)).toHaveTextContent("Panel");
  });

  it("names no panel when the bar has none", () => {
    render(
      <Tabs defaultValue="a" panels={false}>
        <TabsList aria-label="Filter">
          <TabsTrigger value="a">First</TabsTrigger>
          <TabsTrigger value="b">Second</TabsTrigger>
        </TabsList>
      </Tabs>,
    );

    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).not.toHaveAttribute("aria-controls");
    }
  });
});
