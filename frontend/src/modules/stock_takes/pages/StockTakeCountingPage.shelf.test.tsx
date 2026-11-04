import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import * as scanCamera from "@/hooks/useScanCamera";
import { labelsApi } from "@/lib/api/labels";
import type { LabelScanView } from "@/types";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import StockTakeCountingPage from "./StockTakeCountingPage";
import { onePage } from "@/test/mocks/page";

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: vi.fn(),
  useTorchAvailable: () => false,
}));
vi.mock("@/lib/api/labels", () => ({ labelsApi: { scan: vi.fn() } }));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

const line = (id: string, itemId: string, name: string, shelf: string) => ({
  id,
  item_id: itemId,
  item_name: name,
  system_quantity: 2,
  counted_quantity: null as number | null,
  location_id: shelf,
  shelf_location: shelf,
  expected_location_id: null as string | null,
  is_discrepancy: 0,
});

/** A catalogue scan that names the records of one product. */
const productScan = (recordIds: string[]): LabelScanView => ({
  status: "product_stock",
  label_code: "5901234123457",
  action: "show_stock_actions",
  stock_summary: {
    total_quantity: recordIds.length,
    unit: "pcs",
    items: recordIds.map((id) => ({
      id,
      expiry_date: null,
      location: "Rack A",
      quantity: 1,
    })),
  },
});

/** A location label, the way the scan registry answers one. */
const shelfScan = (id: string, name: string): LabelScanView => ({
  status: "storage_context",
  label_code: `LOC-${id}`,
  action: "set_storage_context",
  location: { id, name, icon: "📦" },
});

const countLines = () => [
  line("sti-1", "milk", "Milk", "shelf-1"),
  line("sti-2", "yog-a", "Yoghurt", "shelf-1"),
  line("sti-3", "yog-b", "Yoghurt", "shelf-2"),
];

let lines = countLines();
let patches: { lineId: string; body: Record<string, unknown> }[] = [];
let surpluses: Record<string, unknown>[] = [];
let surplusAnswers: (() => Response)[] = [];
let closes: string[] = [];
let closedLocations: Record<string, unknown>[] = [];

const serve = () => {
  server.use(
    http.get("/api/v1/stock-takes/1", () =>
      HttpResponse.json({
        id: "1",
        name: "Rack count",
        location_id: "rack",
        location_name: "Rack A",
        status: "in_progress",
        blind_mode: false,
        items_count: 3,
        items: lines,
        closed_locations: closedLocations,
        counted_locations: [
          { id: "rack", path: "Rack A" },
          { id: "shelf-1", path: "Rack A / Shelf 1" },
          { id: "shelf-2", path: "Rack A / Shelf 2" },
        ],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    ),
    http.get("/api/v1/locations/rack/items", () =>
      HttpResponse.json(onePage([])),
    ),
    http.post(
      "/api/v1/stock-takes/1/locations/:locationId/close",
      ({ params }) => {
        const shelfId = String(params.locationId);
        closes.push(shelfId);
        const zeroed = lines.filter(
          (row) => row.location_id === shelfId && row.counted_quantity == null,
        ).length;
        lines = lines.map((row) =>
          row.location_id === shelfId && row.counted_quantity == null
            ? { ...row, counted_quantity: 0, is_discrepancy: 1 }
            : row,
        );
        const closure = {
          location_id: shelfId,
          path: `Rack A / ${shelfId}`,
          empty: lines
            .filter((row) => row.location_id === shelfId)
            .every((row) => row.counted_quantity === 0),
          closed_by_name: "Ann Counter",
          closed_at: new Date().toISOString(),
        };
        closedLocations = [closure];
        return HttpResponse.json({ ...closure, counted_as_zero: zeroed });
      },
    ),
    http.patch(
      "/api/v1/stock-takes/1/items/:lineId/count",
      async ({ params, request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patches.push({ lineId: String(params.lineId), body });
        return HttpResponse.json({});
      },
    ),
    http.post("/api/v1/stock-takes/1/items", async ({ request }) => {
      surpluses.push((await request.json()) as Record<string, unknown>);
      const answer = surplusAnswers.shift();
      return answer ? answer() : HttpResponse.json({}, { status: 201 });
    }),
  );
};

const renderPage = async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <MemoryRouter initialEntries={["/stock-takes/1"]}>
      <Routes>
        <Route
          path="/stock-takes/:id"
          element={
            <QueryClientProvider client={queryClient}>
              <PageHeaderContext.Provider
                value={{ data: {}, setHeader: vi.fn() }}
              >
                <StockTakeCountingPage />
              </PageHeaderContext.Provider>
            </QueryClientProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText("Milk");
  return screen.getByTestId("stock-take-counting-input");
};

const enter = (input: HTMLElement, text: string) => {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
};

/** Scan the label of a shelf and wait until the screen says it counts there. */
const standAt = async (input: HTMLElement, id: string, name: string) => {
  vi.mocked(labelsApi.scan).mockResolvedValueOnce(shelfScan(id, name));
  enter(input, `LOC-${id}`);
  return screen.findByTestId("stock-take-shelf");
};

beforeEach(() => {
  signInWith(["stock_takes:write"]);
  lines = countLines();
  patches = [];
  surpluses = [];
  surplusAnswers = [];
  closes = [];
  closedLocations = [];
  vi.mocked(toast.error).mockReset();
  vi.mocked(toast.success).mockReset();
  vi.mocked(labelsApi.scan).mockReset();
  vi.mocked(scanCamera.useScanCamera).mockImplementation(
    () =>
      ({
        scannerError: null,
        isCameraActive: false,
        isCameraRunning: false,
        setIsCameraActive: vi.fn(),
        restartCamera: vi.fn(),
        toggleTorch: vi.fn(),
        isTorchOn: false,
      }) as unknown as ReturnType<typeof scanCamera.useScanCamera>,
  );
  serve();
});

describe("counting a stock take shelf by shelf", () => {
  it("names the scanned shelf and narrows the list to its rows", async () => {
    const input = await renderPage();

    const bar = await standAt(input, "shelf-2", "Shelf 2");

    expect(bar).toHaveTextContent("Rack A / Shelf 2");
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();
    expect(screen.getAllByText("Yoghurt")).toHaveLength(1);
  });

  it("refuses a location outside the count, naming the counted one", async () => {
    const input = await renderPage();
    await standAt(input, "shelf-2", "Shelf 2");
    vi.mocked(labelsApi.scan).mockResolvedValue(shelfScan("cellar", "Cellar"));

    enter(input, "LOC-cellar");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This location is not part of the count of Rack A.",
      ),
    );
    // Standing outside the count, the counter is no longer at that shelf.
    expect(screen.queryByTestId("stock-take-shelf")).not.toBeInTheDocument();
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("counts the current shelf's row without asking which one", async () => {
    const input = await renderPage();
    await standAt(input, "shelf-2", "Shelf 2");
    vi.mocked(labelsApi.scan).mockResolvedValue(
      productScan(["yog-a", "yog-b"]),
    );

    enter(input, "5901234123457");

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      lineId: "sti-3",
      body: { counted_quantity: 1 },
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("records goods expected on another shelf as found on this one", async () => {
    const input = await renderPage();
    await standAt(input, "shelf-2", "Shelf 2");
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));

    enter(input, "5901234123457");

    await waitFor(() => expect(surpluses).toHaveLength(1));
    expect(surpluses[0]).toMatchObject({
      item_id: "milk",
      counted_quantity: 1,
      location_id: "shelf-2",
    });
    expect(patches).toHaveLength(0);
  });

  it("counts a second find on that shelf onto the row the first one opened", async () => {
    surplusAnswers = [
      () =>
        HttpResponse.json(
          {
            id: "sti-9",
            item_id: "milk-on-2",
            counted_quantity: 1,
            location_id: "shelf-2",
          },
          { status: 201 },
        ),
      () =>
        HttpResponse.json(
          {
            detail: {
              code: "STOCK_TAKE_ITEM_ALREADY_EXISTS",
              message: "Already on the count",
              stock_take_item_id: "sti-9",
              item_id: "milk-on-2",
            },
          },
          { status: 409 },
        ),
    ];
    const input = await renderPage();
    await standAt(input, "shelf-2", "Shelf 2");
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));

    enter(input, "5901234123457");
    await waitFor(() => expect(surpluses).toHaveLength(1));
    enter(input, "5901234123457");

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      lineId: "sti-9",
      body: { counted_quantity: 2 },
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("counts a unit that owns its identity on the shelf it was found on", async () => {
    // The server moves the unit's one row to the shelf it was found on and
    // keeps the shelf its record stands on.
    const moved = {
      ...line("sti-1", "milk", "Milk", "shelf-2"),
      counted_quantity: 1,
      expected_location_id: "shelf-1",
    };
    surplusAnswers = [
      () => {
        lines = [moved, ...lines.slice(1)];
        return HttpResponse.json(moved, { status: 201 });
      },
    ];
    const input = await renderPage();
    await standAt(input, "shelf-2", "Shelf 2");
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));

    enter(input, "5901234123457");

    await waitFor(() => expect(surpluses).toHaveLength(1));
    expect(surpluses[0]).toMatchObject({
      item_id: "milk",
      location_id: "shelf-2",
    });
    // Counted where it was found: the shelf's list shows it, and the next
    // scan counts that row instead of recording another find.
    expect(await screen.findByText("Milk")).toBeInTheDocument();
    enter(input, "5901234123457");
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      lineId: "sti-1",
      body: { counted_quantity: 2 },
    });
    expect(surpluses).toHaveLength(1);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("asks why a unit counted in full stood on another shelf", async () => {
    // Moved and counted at the number its record holds: the difference is
    // the shelf alone, and a tolerance refuses to close until it has a
    // reason, so the card must ask for one.
    lines = [
      {
        ...line("sti-1", "milk", "Milk", "shelf-2"),
        counted_quantity: 2,
        expected_location_id: "shelf-1",
        is_discrepancy: 1,
      },
      ...lines.slice(1),
    ];
    await renderPage();

    expect(screen.getByTestId("discrepancy-reason-code")).toBeInTheDocument();
  });

  it("says a shelf with no rows expected nothing there", async () => {
    const input = await renderPage();

    await standAt(input, "rack", "Rack A");

    expect(
      screen.getByText(
        "Nothing was expected at this location. Scan what stands there.",
      ),
    ).toBeInTheDocument();
  });

  it("does not claim a shelf expected nothing when a filter hides its rows", async () => {
    const input = await renderPage();
    await userEvent.click(
      screen.getByRole("button", { name: /Discrepancies/ }),
    );

    await standAt(input, "shelf-2", "Shelf 2");

    expect(
      screen.queryByText(/Nothing was expected at this location/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("The filters above hide this location's rows."),
    ).toBeInTheDocument();
  });

  it("goes back to the whole location when the shelf is left", async () => {
    const input = await renderPage();
    const bar = await standAt(input, "shelf-2", "Shelf 2");

    await userEvent.click(
      within(bar).getByRole("button", { name: "Whole location" }),
    );

    expect(screen.queryByTestId("stock-take-shelf")).not.toBeInTheDocument();
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getAllByText("Yoghurt")).toHaveLength(2);
  });
});

describe("closing the shelf the count stands at", () => {
  /** Press "Close location" on the bar and answer the question it asks. */
  const closeShelf = async (bar: HTMLElement) => {
    await userEvent.click(
      within(bar).getByRole("button", { name: "Close location" }),
    );
    return screen.findByRole("alertdialog");
  };

  it("names how many rows it counts as 0, and shows them counted", async () => {
    const input = await renderPage();
    const bar = await standAt(input, "shelf-1", "Shelf 1");

    const dialog = await closeShelf(bar);
    // How many rows, never what they held: the same words in a blind count.
    expect(dialog).toHaveTextContent(
      "2 rows at Rack A / Shelf 1 were not counted. Closing the location counts them as 0 — shortages in the report.",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close location" }),
    );

    await waitFor(() => expect(closes).toEqual(["shelf-1"]));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Rack A / Shelf 1 closed: 2 rows counted as 0.",
      ),
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Counted quantity of Milk")).toHaveValue(
        "0",
      );
      expect(screen.getByLabelText("Counted quantity of Yoghurt")).toHaveValue(
        "0",
      );
    });
    expect(
      await within(screen.getByTestId("stock-take-shelf")).findByText(
        "Confirmed empty by Ann Counter",
      ),
    ).toBeInTheDocument();
    // Nothing typed is left unsaved by the zeros the server wrote.
    expect(patches).toHaveLength(0);
  });

  it("confirms a shelf with no rows as counted and empty", async () => {
    const input = await renderPage();
    const bar = await standAt(input, "rack", "Rack A");

    const dialog = await closeShelf(bar);

    expect(dialog).toHaveTextContent(
      "Nothing was found at Rack A. Confirm it as counted and empty?",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close location" }),
    );
    await waitFor(() => expect(closes).toEqual(["rack"]));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Rack A confirmed as empty."),
    );
  });

  it("does not close a shelf over a number still in its box", async () => {
    const input = await renderPage();
    const bar = await standAt(input, "shelf-2", "Shelf 2");
    fireEvent.change(screen.getByLabelText("Counted quantity of Yoghurt"), {
      target: { value: "3" },
    });

    await userEvent.click(
      within(bar).getByRole("button", { name: "Close location" }),
    );

    expect(toast.error).toHaveBeenCalledWith(
      "One number at this location has not been saved. Save it before closing the location.",
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(closes).toHaveLength(0);
  });

  it("closes nothing when the question is declined", async () => {
    const input = await renderPage();
    const bar = await standAt(input, "shelf-2", "Shelf 2");

    const dialog = await closeShelf(bar);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );

    expect(closes).toHaveLength(0);
  });
});
