import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { entry, shelfNode } from "@/test/factories/occupancy";
import { OccupancyTree, VIRTUALISE_FROM } from "./OccupancyTree";

// jsdom has no layout, so the virtualizer would see a window of zero height.
// Hand the tree a window of rows 40..49 and check that is all it draws.
vi.mock("@tanstack/react-virtual", () => ({
  useWindowVirtualizer: ({ count }: { count: number }) => ({
    options: { scrollMargin: 0 },
    measureElement: () => undefined,
    getTotalSize: () => count * 44,
    getVirtualItems: () =>
      Array.from({ length: 10 }, (_, i) => ({
        index: 40 + i,
        start: (40 + i) * 44,
        end: (41 + i) * 44,
      })),
  }),
}));

const nodes = Array.from({ length: VIRTUALISE_FROM + 50 }, (_, i) =>
  shelfNode(`S${i}`, "Hall", 1, i, [entry("Rice", "10", "50")]),
);

const props = {
  folded: new Set<string>(),
  opened: new Set<string>(),
  entries: new Map(),
  failures: new Map(),
  hits: null,
  onToggleFold: vi.fn(),
  onToggleOpen: vi.fn(),
  onOpenSettings: vi.fn(),
};

describe("OccupancyTree", () => {
  it("draws only the rows in view from a hundred rows on, with spacers for the rest", () => {
    const { container } = render(<OccupancyTree nodes={nodes} {...props} />);

    expect(screen.getByText("S40")).toBeInTheDocument();
    expect(screen.getByText("S49")).toBeInTheDocument();
    expect(screen.queryByText("S0")).not.toBeInTheDocument();
    expect(screen.queryByText("S50")).not.toBeInTheDocument();
    const spacers = container.querySelectorAll('tr[aria-hidden="true"]');
    expect(spacers).toHaveLength(2);
    expect((spacers[0] as HTMLElement).style.height).toBe(`${40 * 44}px`);
  });

  it("draws every row below the threshold", () => {
    render(<OccupancyTree nodes={nodes.slice(0, 20)} {...props} />);

    expect(screen.getByText("S0")).toBeInTheDocument();
    expect(screen.getByText("S19")).toBeInTheDocument();
  });
});
