import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  onTestFinished,
  vi,
} from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import type { PutawayOccupancyOverview } from "@/modules/warehouse/api/putaway";
import {
  containerNode,
  entry,
  floor,
  shelfNode,
  shelfRead,
  stockRowsMatching,
} from "@/test/factories/occupancy";
import OccupancyPage from "./OccupancyPage";

/** Drive `useMediaQuery`: the map is for a desktop, a phone gets the tree. */
function setWide(wide: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: wide,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

/**
 * The floor's overview, each shelf's own read and the stock list's search,
 * answered from the shelves the factory built.
 */
function serve(overview: PutawayOccupancyOverview = floor) {
  const reads = vi.fn();
  const shelfReads = vi.fn();
  const searches = vi.fn();
  server.use(
    http.get("/api/v1/warehouse/putaway/occupancy", () => {
      reads();
      return HttpResponse.json(overview);
    }),
    http.get("/api/v1/warehouse/putaway/occupancy/:id", ({ params }) => {
      shelfReads(params.id);
      return HttpResponse.json(shelfRead(String(params.id)));
    }),
    http.get("/api/v1/stock-quants", ({ request }) => {
      const search = new URL(request.url).searchParams.get("search") ?? "";
      searches(search);
      return HttpResponse.json(stockRowsMatching(search));
    }),
  );
  return Object.assign(reads, { shelfReads, searches });
}

beforeEach(() => {
  signInWith(["warehouse:read", "warehouse:write", "locations:write"]);
  setWide(true);
});

afterEach(() => {
  signOut();
});

const rowOf = (name: string) => screen.getByText(name).closest("tr")!;
const findRow = async (name: string) =>
  (await screen.findByText(name)).closest("tr")!;

describe("OccupancyPage — the tree", () => {
  it("reads the whole floor with one request and shows a bar and a number per limited shelf", async () => {
    const reads = serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    expect(reads).toHaveBeenCalledTimes(1);
    // 26 of 50 kg: a bar, and always the number beside it.
    expect(
      within(rowOf("Fridge A")).getByRole("meter", { name: "Fridge A" }),
    ).toHaveAttribute("aria-valuenow", "52");
    expect(within(rowOf("Fridge A")).getByText("52%")).toBeInTheDocument();
    // Over the limit: the bar is full, the number says how far over.
    expect(
      within(rowOf("Fridge C")).getByRole("meter", { name: "Fridge C" }),
    ).toHaveAttribute("aria-valuenow", "100");
    expect(within(rowOf("Fridge C")).getByText("120%")).toBeInTheDocument();
  });

  it("draws no bar for a shelf without a limit and says so; an empty one says empty", async () => {
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Rack 1");
    const rack = within(rowOf("Rack 1"));
    expect(rack.queryByRole("meter")).not.toBeInTheDocument();
    expect(rack.getByText("No limit")).toBeInTheDocument();
    expect(rack.getByText(/30\s*kg · Flour|30 kg · Flour/)).toBeInTheDocument();
    const empty = within(rowOf("Fridge D"));
    expect(empty.queryByRole("meter")).not.toBeInTheDocument();
    expect(empty.getAllByText("Empty").length).toBeGreaterThan(0);
  });

  it("summarises a zone and averages over its limited shelves only", async () => {
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Cold");
    const zone = within(rowOf("Cold"));
    expect(zone.getByText("83% avg.")).toBeInTheDocument();
    expect(
      zone.getByText("4 locations · 3 with a limit · 2 full · 1 empty"),
    ).toBeInTheDocument();
    // A zone with nothing limited has no average to show.
    expect(within(rowOf("Dry")).queryByText(/avg\./)).not.toBeInTheDocument();
  });

  it("shows the counters from the server's totals", async () => {
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    const counters = screen.getByText("Over the limit", {
      selector: "dt",
    }).parentElement!;
    expect(within(counters).getByText("1")).toBeInTheDocument();
  });

  it("folds a zone away", async () => {
    const user = userEvent.setup();
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.click(screen.getByRole("button", { name: "Collapse Cold" }));
    expect(screen.queryByText("Fridge A")).not.toBeInTheDocument();
    expect(screen.getByText("Rack 1")).toBeInTheDocument();
  });

  it("lists each product's share when a mixed shelf is opened", async () => {
    const user = userEvent.setup();
    const reads = serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge B");
    expect(screen.queryByText("Butter")).not.toBeInTheDocument();
    // The floor's answer counts the shelf's products; the shelf is read on
    // its own when the reader opens it, and only then.
    expect(reads.shelfReads).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Expand Fridge B" }));
    expect(await screen.findByText("Butter")).toBeInTheDocument();
    expect(screen.getByText("30% of its limit")).toBeInTheDocument();
    expect(reads.shelfReads.mock.calls).toEqual([["Fridge B"]]);
  });

  it("names the products of a shelf it does not list", async () => {
    serve({
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 1,
          with_limit: 0,
          full: 0,
          over: 0,
          empty: 0,
          average_fill: null,
        }),
        shelfNode("Bin", "Hall", 1, 0, [
          entry("Salt", "7", null),
          entry("Rice", "3", null),
          entry("Oats", "2", null),
        ]),
      ],
      totals: floor.totals,
    });
    render(<OccupancyPage />);

    await screen.findByText("Bin");
    expect(within(rowOf("Bin")).getByText("3 products")).toBeInTheDocument();
  });

  it("filters to the shelves over their limit and keeps the way to them", async () => {
    const user = userEvent.setup();
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.click(screen.getByRole("tab", { name: "Over the limit" }));
    expect(screen.getByText("Fridge C")).toBeInTheDocument();
    expect(screen.getByText("Cold")).toBeInTheDocument();
    expect(screen.queryByText("Fridge A")).not.toBeInTheDocument();
    expect(screen.queryByText("Rack 1")).not.toBeInTheDocument();
  });

  it("finds where a product lies, with its quantity, and hides the rest", async () => {
    const user = userEvent.setup();
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    await waitFor(() =>
      expect(screen.queryByText("Fridge A")).not.toBeInTheDocument(),
    );
    expect(within(rowOf("Fridge B")).getByText("12 pcs")).toBeInTheDocument();
    expect(within(rowOf("Fridge C")).getByText("48 pcs")).toBeInTheDocument();
  });

  it("shows the matching shelves of a folded zone while a search runs", async () => {
    const user = userEvent.setup();
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.click(screen.getByRole("button", { name: "Collapse Cold" }));
    expect(screen.queryByText("Fridge B")).not.toBeInTheDocument();
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    expect(await screen.findByText("Fridge B")).toBeInTheDocument();
    expect(within(rowOf("Fridge B")).getByText("12 pcs")).toBeInTheDocument();
    // The search over, the fold is back as the reader left it.
    await user.clear(
      screen.getByPlaceholderText("Where is… product name or code"),
    );
    await waitFor(() =>
      expect(screen.queryByText("Fridge B")).not.toBeInTheDocument(),
    );
  });

  it("asks the server where the product lies", async () => {
    const user = userEvent.setup();
    const reads = serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    await waitFor(() => expect(reads.searches).toHaveBeenCalledWith("gouda"));
    // Typing is not a request per letter.
    expect(reads.searches).toHaveBeenCalledTimes(1);
  });

  it("says when the search found more than it marks", async () => {
    const user = userEvent.setup();
    serve();
    server.use(
      http.get("/api/v1/stock-quants", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search") ?? "";
        return HttpResponse.json({
          ...stockRowsMatching(search),
          total: 900,
          has_more: true,
        });
      }),
    );
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    expect(
      await screen.findByText(
        "More than 500 matches — type more of the name to narrow the search.",
      ),
    ).toBeInTheDocument();
  });

  it("says the search failed, offers it again and does not show the whole floor instead", async () => {
    const user = userEvent.setup();
    serve();
    let fail = true;
    server.use(
      http.get("/api/v1/stock-quants", ({ request }) => {
        if (fail) return HttpResponse.json({}, { status: 500 });
        const search = new URL(request.url).searchParams.get("search") ?? "";
        return HttpResponse.json(stockRowsMatching(search));
      }),
    );
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The search could not be run");
    // A failed search is not an empty one: the floor it did not filter is
    // not shown as if it were the answer.
    expect(screen.queryByText("Fridge A")).not.toBeInTheDocument();
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(
      within(await findRow("Fridge B")).getByText("12 pcs"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Fridge A")).not.toBeInTheDocument();
  });

  it("says a shelf's contents could not be read and offers to read them again", async () => {
    const user = userEvent.setup();
    serve();
    let fail = true;
    server.use(
      http.get("/api/v1/warehouse/putaway/occupancy/:id", ({ params }) =>
        fail
          ? HttpResponse.json({}, { status: 500 })
          : HttpResponse.json(shelfRead(String(params.id))),
      ),
    );
    render(<OccupancyPage />);

    await screen.findByText("Fridge B");
    await user.click(screen.getByRole("button", { name: "Expand Fridge B" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The location's contents could not be read",
    );
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Butter")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    const user = userEvent.setup();
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "zzz",
    );
    expect(await screen.findByText("No location matches.")).toBeInTheDocument();
  });

  it("asks for a floor to be set up when there is none", async () => {
    serve({ nodes: [], totals: floor.totals });
    render(<OccupancyPage />);

    expect(await screen.findByText("No locations yet")).toBeInTheDocument();
  });
});

describe("OccupancyPage — the map", () => {
  async function openMap() {
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("Fridge A");
    await user.click(screen.getByRole("button", { name: /grid/i }));
    return user;
  }

  it("shows each zone as a block with a tile per shelf and its percentage", async () => {
    serve();
    await openMap();

    const block = screen.getByRole("region", { name: "Cold" });
    expect(
      within(block).getByRole("button", { name: "Fridge A: 52% full" }),
    ).toHaveTextContent("52%");
    expect(
      within(block).getByRole("button", { name: "Fridge D: Empty" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Dry" })).getByRole("button", {
        name: "Rack 1: No limit",
      }),
    ).toBeInTheDocument();
  });

  it("shows what lies on a shelf, with the shares, when its tile is pressed", async () => {
    serve();
    const user = await openMap();

    await user.click(
      screen.getByRole("button", { name: "Fridge B: 30% full" }),
    );
    const panel = screen.getByRole("complementary");
    expect(within(panel).getByText("Gouda")).toBeInTheDocument();
    expect(within(panel).getByText("Butter")).toBeInTheDocument();
    expect(within(panel).getByText("Total fill 30%")).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", {
        name: "Set limits for this location",
      }),
    ).toBeInTheDocument();
  });

  it("says when a picked shelf's contents could not be read", async () => {
    serve();
    let fail = true;
    server.use(
      http.get("/api/v1/warehouse/putaway/occupancy/:id", ({ params }) =>
        fail
          ? HttpResponse.json({}, { status: 500 })
          : HttpResponse.json(shelfRead(String(params.id))),
      ),
    );
    const user = await openMap();

    await user.click(
      screen.getByRole("button", { name: "Fridge B: 30% full" }),
    );
    const panel = screen.getByRole("complementary");
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent(
      "The location's contents could not be read",
    );
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByText("Butter")).toBeInTheDocument();
  });

  it("switches a zone with many shelves to small tiles that keep their names", async () => {
    const crowded: PutawayOccupancyOverview = {
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 60,
          with_limit: 60,
          full: 0,
          over: 0,
          empty: 0,
          average_fill: 20,
        }),
        ...Array.from({ length: 60 }, (_, i) =>
          shelfNode(`S${i}`, "Hall", 1, i, [entry("Rice", "10", "50")]),
        ),
      ],
      totals: floor.totals,
    };
    serve(crowded);
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("S0");
    await user.click(screen.getByRole("button", { name: /grid/i }));

    const tile = screen.getByRole("button", { name: "S7: 20% full" });
    // Dense: the percentage stays on the tile, the name moves to title/label.
    expect(tile).toHaveTextContent("20%");
    expect(tile).not.toHaveTextContent("S7");
    expect(tile).toHaveAttribute("title", "S7: 20% full");
  });

  it("keeps the quantity on small tiles: a shelf without a limit and a search hit", async () => {
    const crowded: PutawayOccupancyOverview = {
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 60,
          with_limit: 59,
          full: 0,
          over: 0,
          empty: 0,
          average_fill: 20,
        }),
        shelfNode("Open", "Hall", 1, 0, [entry("Salt", "7", null)]),
        ...Array.from({ length: 59 }, (_, i) =>
          shelfNode(`S${i}`, "Hall", 1, i + 1, [entry("Rice", "10", "50")]),
        ),
      ],
      totals: floor.totals,
    };
    serve(crowded);
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("S0");
    await user.click(screen.getByRole("button", { name: /grid/i }));

    // Dense, no limit: the quantity is on the tile, not only in its label.
    expect(
      screen.getByRole("button", { name: "Open: No limit" }),
    ).toHaveTextContent("7 pcs");

    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "rice",
    );
    const hit = await screen.findByRole("button", {
      name: "S7: 20% full · 10 pcs",
    });
    expect(hit).toHaveTextContent("20%");
    expect(hit).toHaveTextContent("10 pcs");
  });

  it("says empty on the tile of an empty shelf that has a limit, and 0% nowhere", async () => {
    serve({
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 1,
          with_limit: 1,
          full: 0,
          over: 0,
          empty: 1,
          average_fill: 0,
        }),
        shelfNode("Bare", "Hall", 1, 0, [entry("Rice", "0", "50")]),
      ],
      totals: floor.totals,
    });
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("Bare");
    await user.click(screen.getByRole("button", { name: /grid/i }));

    const tile = screen.getByRole("button", { name: "Bare: Empty" });
    expect(tile).toHaveTextContent("Empty");
    expect(tile).not.toHaveTextContent("0%");
  });

  it("prints the quantity on the tile of a shelf without a limit", async () => {
    serve();
    await openMap();

    expect(
      screen.getByRole("button", { name: "Rack 1: No limit" }),
    ).toHaveTextContent("30 kg");
  });

  it("prints the quantity the search found on each matching tile", async () => {
    serve();
    const user = await openMap();

    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    const b = await screen.findByRole("button", {
      name: "Fridge B: 30% full · 12 pcs",
    });
    expect(b).toHaveTextContent("12 pcs");
    expect(
      screen.getByRole("button", { name: "Fridge C: 120% full · 48 pcs" }),
    ).toHaveTextContent("48 pcs");
  });

  it("brings the panel into view when a tile is picked, and gives a dense zone the full row", async () => {
    const crowded: PutawayOccupancyOverview = {
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 60,
          with_limit: 60,
          full: 0,
          over: 0,
          empty: 0,
          average_fill: 20,
        }),
        ...Array.from({ length: 60 }, (_, i) =>
          shelfNode(`S${i}`, "Hall", 1, i, [entry("Rice", "10", "50")]),
        ),
      ],
      totals: floor.totals,
    };
    serve(crowded);
    const scroll = vi.fn();
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    onTestFinished(() => {
      HTMLElement.prototype.scrollIntoView = original;
    });
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("S0");
    await user.click(screen.getByRole("button", { name: /grid/i }));

    // Sixty shelves are a screenful at one third of the row; across it they
    // are a few rows.
    expect(screen.getByRole("region", { name: "Hall" }).className).toContain(
      "xl:col-span-3",
    );

    expect(scroll).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "S7: 20% full" }));
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(screen.getByRole("complementary"));
  });

  it("counts the matching shelves in the singular when one holds the product", async () => {
    const small: PutawayOccupancyOverview = {
      nodes: [
        containerNode("Hall", null, 0, {
          shelves: 2,
          with_limit: 2,
          full: 0,
          over: 0,
          empty: 0,
          average_fill: 20,
        }),
        shelfNode("S1", "Hall", 1, 0, [entry("Rice", "10", "50")]),
        shelfNode("S2", "Hall", 1, 1, [entry("Salt", "10", "50")]),
      ],
      totals: floor.totals,
    };
    serve(small);
    const user = userEvent.setup();
    render(<OccupancyPage />);
    await screen.findByText("S1");

    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "rice",
    );
    await waitFor(() =>
      expect(screen.queryByText("S2")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("1 location")).toBeInTheDocument();
  });

  it("marks the shelves that hold the searched product", async () => {
    serve();
    const user = await openMap();

    await user.type(
      screen.getByPlaceholderText("Where is… product name or code"),
      "gouda",
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /Fridge A/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Fridge B: 30% full · 12 pcs" })
        .className,
    ).toContain("outline-yellow-400");
    // A class name is not a drawn ring: tailwind-merge dropped the bare
    // `outline` beside the arbitrary width once, leaving a width and no style.
    // The style has to survive in the merged class list.
    expect(
      screen.getByRole("button", { name: "Fridge B: 30% full · 12 pcs" })
        .className,
    ).toContain("[outline-style:solid]");
  });
});

describe("OccupancyPage — on a phone", () => {
  it("offers the tree only", async () => {
    setWide(false);
    serve();
    render(<OccupancyPage />);

    await screen.findByText("Fridge A");
    expect(
      screen.queryByRole("button", { name: /grid/i }),
    ).not.toBeInTheDocument();
  });
});
