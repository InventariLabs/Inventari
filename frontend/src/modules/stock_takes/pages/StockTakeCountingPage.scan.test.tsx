import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  act,
  render,
  screen,
  waitFor,
  within,
  fireEvent,
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
import { scanWithHardwareScanner } from "@/test/scanner";
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

let cameraOnCode: (code: string) => void = () => {};
const restartCamera = vi.fn();

const line = (id: string, itemId: string, name: string, counted: number) => ({
  id,
  item_id: itemId,
  item_name: name,
  system_quantity: 2,
  counted_quantity: counted,
  shelf_location: `A-${id}`,
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
      location: "Fridge",
      quantity: 1,
    })),
  },
});

const unrecognized = () =>
  Object.assign(new Error("not recognized"), {
    isAxiosError: true,
    response: {
      status: 404,
      data: { detail: { code: "SCAN_UNRECOGNIZED", message: "Unknown code" } },
    },
  });

let patches: { lineId: string; body: Record<string, unknown> }[] = [];
let surpluses: Record<string, unknown>[] = [];

const serve = (blindMode = false) => {
  server.use(
    http.get("/api/v1/stock-takes/1", () =>
      HttpResponse.json({
        id: "1",
        name: "Stock Take 1",
        location_id: "loc-1",
        location_name: "Fridge",
        status: "in_progress",
        blind_mode: blindMode,
        items_count: 3,
        items: [
          line("sti-1", "milk", "Milk", 2),
          line("sti-2", "yog-a", "Yoghurt", 0),
          line("sti-3", "yog-b", "Yoghurt", 0),
        ],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    ),
    http.get("/api/v1/locations/loc-1/items", () =>
      HttpResponse.json(
        onePage([
          {
            id: "milk",
            name: "Milk",
            quantity: "2",
            location_id: "loc-1",
          },
          {
            id: "yog-a",
            name: "Yoghurt",
            quantity: "1",
            location_id: "loc-1",
          },
          {
            id: "yog-b",
            name: "Yoghurt",
            quantity: "1",
            location_id: "loc-1",
          },
          { id: "jam", name: "Jam", quantity: "1", location_id: "loc-1" },
        ]),
      ),
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
      return HttpResponse.json({}, { status: 201 });
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

/** What a person types and confirms with Enter. Typed key by key, a gap the
 *  test machine adds under load splits the "scanner burst" and the scanner
 *  hook takes the tail of the code instead. */
const enter = (input: HTMLElement, text: string) => {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
};

beforeEach(() => {
  signInWith(["stock_takes:write"]);
  patches = [];
  surpluses = [];
  restartCamera.mockReset();
  vi.mocked(labelsApi.scan).mockReset();
  vi.mocked(scanCamera.useScanCamera).mockImplementation(
    ({ onCodeScanned }) => {
      cameraOnCode = onCodeScanned;
      return {
        scannerError: null,
        isCameraActive: true,
        isCameraRunning: true,
        setIsCameraActive: vi.fn(),
        restartCamera,
        toggleTorch: vi.fn(),
        isTorchOn: false,
      } as unknown as ReturnType<typeof scanCamera.useScanCamera>;
    },
  );
  serve();
});

describe("counting by scanning on the stock take screen", () => {
  it("counts one more and saves when Enter takes a catalogue barcode with one record here", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk", "far"]));
    const input = await renderPage();

    enter(input, "5901234123457");

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      lineId: "sti-1",
      body: { counted_quantity: 3 },
    });
    expect(labelsApi.scan).toHaveBeenCalledWith("5901234123457");
    expect(input).toHaveValue("");
  });

  it("tells the counter when the server refuses the count a scan just made", async () => {
    // A scan that beeps and saves nothing sends the counter to the next bay
    // believing the shelf is done.
    vi.mocked(toast.error).mockClear();
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));
    server.use(
      http.patch(
        "/api/v1/stock-takes/1/items/:lineId/count",
        () => new HttpResponse(null, { status: 403 }),
      ),
    );
    const input = await renderPage();

    enter(input, "5901234123457");

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(patches).toHaveLength(0);
  });

  it("counts a record's own label read by a hardware scanner", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "assigned",
      label_code: "AB12CD",
      action: "show_quick_actions",
      item: { id: "milk", name: "Milk" } as LabelScanView["item"],
    });
    const input = await renderPage();
    input.focus();

    scanWithHardwareScanner("AB12CD", input);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].body).toMatchObject({ counted_quantity: 3 });
  });

  it("asks which record was meant when the product has several here", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(
      productScan(["yog-a", "yog-b"]),
    );
    const input = await renderPage();

    enter(input, "5900000000001");

    const chooser = await screen.findByRole("dialog");
    expect(patches).toHaveLength(0);
    const options = within(chooser).getAllByRole("button", {
      name: /Yoghurt/,
    });
    expect(options).toHaveLength(2);
    await userEvent.click(within(chooser).getByText("A-sti-3"));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      lineId: "sti-3",
      body: { counted_quantity: 1 },
    });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("keeps the expected quantity out of the chooser in blind mode", async () => {
    serve(true);
    vi.mocked(labelsApi.scan).mockResolvedValue(
      productScan(["yog-a", "yog-b"]),
    );
    const input = await renderPage();

    enter(input, "5900000000001");

    const chooser = await screen.findByRole("dialog");
    expect(within(chooser).queryByText(/expected/i)).not.toBeInTheDocument();
    expect(within(chooser).queryByText("2")).not.toBeInTheDocument();
  });

  it("registers a product found in this place but missing from the list as a surplus of one", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["jam"]));
    const input = await renderPage();

    enter(input, "5900000000002");

    await waitFor(() => expect(surpluses).toHaveLength(1));
    expect(surpluses[0]).toMatchObject({
      item_id: "jam",
      counted_quantity: 1,
    });
  });

  it("leaves a code nothing recognized in the search box and saves nothing", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(unrecognized());
    const input = await renderPage();

    enter(input, "mil");

    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalledWith("mil"));
    expect(input).toHaveValue("mil");
    expect(patches).toHaveLength(0);
    expect(surpluses).toHaveLength(0);
  });

  it("counts what the camera reads once it has been opened", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));
    await renderPage();
    expect(document.getElementById("qr-reader")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /camera/i }));

    expect(restartCamera).toHaveBeenCalled();
    expect(document.getElementById("qr-reader")).not.toBeNull();
    // The camera calls back from outside React, as the decoder does.
    await act(async () => cameraOnCode("5901234123457"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].body).toMatchObject({ counted_quantity: 3 });
  });

  it("lists what is in the counted place before the rest of the organization", async () => {
    server.use(
      http.get("/api/v1/items", ({ request }) => {
        const storageId = new URL(request.url).searchParams.get("location_id");
        const items = [
          {
            id: "far",
            name: "Milk powder",
            quantity: "1",
            location_id: "loc-9",
          },
          {
            id: "milk",
            name: "Milk",
            quantity: "2",
            location_id: "loc-1",
          },
        ];
        return HttpResponse.json({
          items: storageId
            ? items.filter((item) => item.location_id === storageId)
            : items,
          total: items.length,
        });
      }),
    );
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "mi" } });

    const here = await screen.findByRole("group", { name: /this count/i });
    const elsewhere = screen.getByRole("group", { name: /elsewhere/i });
    expect(within(here).getByText("Milk")).toBeInTheDocument();
    expect(within(elsewhere).getByText("Milk powder")).toBeInTheDocument();
    expect(
      here.compareDocumentPosition(elsewhere) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("finds a record in the counted place even when the organization page is full of matches elsewhere", async () => {
    const elsewhere = Array.from({ length: 100 }, (_, index) => ({
      id: `far-${index}`,
      name: `Scope needle elsewhere ${index}`,
      quantity: "1",
      location_id: `loc-${index + 2}`,
    }));
    const here = {
      id: "needle-here",
      name: "Scope needle here",
      quantity: "1",
      location_id: "loc-1",
    };
    server.use(
      http.get("/api/v1/items", ({ request }) => {
        const storageId = new URL(request.url).searchParams.get("location_id");
        // The organization's first page is cut before the one record that
        // stands in the counted place.
        return HttpResponse.json({
          items: storageId === "loc-1" ? [here] : elsewhere,
          total: storageId === "loc-1" ? 1 : 101,
        });
      }),
    );
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "scope needle" } });

    const hereGroup = await screen.findByRole("group", {
      name: /this count/i,
    });
    expect(
      within(hereGroup).getByText("Scope needle here"),
    ).toBeInTheDocument();
    const elsewhereGroup = screen.getByRole("group", {
      name: /elsewhere/i,
    });
    expect(
      within(elsewhereGroup).getByText("Scope needle elsewhere 0"),
    ).toBeInTheDocument();
  });

  it("counts a second code that arrives while the first lookup is still in flight", async () => {
    let answerFirst: ((view: LabelScanView) => void) | undefined;
    vi.mocked(labelsApi.scan)
      .mockImplementationOnce(
        () =>
          new Promise<LabelScanView>((resolve) => {
            answerFirst = resolve;
          }),
      )
      .mockResolvedValue(productScan(["milk"]));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "5901234123457" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalledTimes(1));

    // The next item is scanned before the first lookup has answered. It is a
    // count of its own and must not be dropped as a repeated camera frame.
    fireEvent.change(input, { target: { value: "REV-COUNT1" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(labelsApi.scan).toHaveBeenCalledTimes(1);

    await act(async () => answerFirst?.(productScan(["milk"])));

    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches.map((entry) => entry.body.counted_quantity)).toEqual([3, 4]);
  });

  it("stores the later of two scans even when the earlier save answers last", async () => {
    // The count is an absolute number, so the server keeps whichever save
    // reaches it last. Held open here, the first save is the slow one.
    let releaseFirst: (() => void) | undefined;
    let stored: unknown;
    server.use(
      http.patch(
        "/api/v1/stock-takes/1/items/:lineId/count",
        async ({ params, request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          patches.push({ lineId: String(params.lineId), body });
          if (patches.length === 1) {
            await new Promise<void>((resolve) => {
              releaseFirst = resolve;
            });
          }
          stored = body.counted_quantity;
          return HttpResponse.json({});
        },
      ),
    );
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["milk"]));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "5901234123457" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(patches).toHaveLength(1));
    fireEvent.change(input, { target: { value: "5901234123457" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalledTimes(2));

    // The second save waits for the first instead of overtaking it.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(patches).toHaveLength(1);

    await act(async () => releaseFirst?.());

    await waitFor(() => expect(patches).toHaveLength(2));
    await waitFor(() => expect(stored).toBe(4));
    expect(patches.map((entry) => entry.body.counted_quantity)).toEqual([3, 4]);
  });

  it("counts a second scan of a new surplus onto the row the first one created", async () => {
    let releaseFirst: (() => void) | undefined;
    server.use(
      http.post("/api/v1/stock-takes/1/items", async ({ request }) => {
        surpluses.push((await request.json()) as Record<string, unknown>);
        await new Promise<void>((resolve) => {
          releaseFirst = resolve;
        });
        return HttpResponse.json(
          { id: "sti-jam", item_id: "jam", counted_quantity: 1 },
          { status: 201 },
        );
      }),
    );
    vi.mocked(labelsApi.scan).mockResolvedValue(productScan(["jam"]));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "5900000000002" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(surpluses).toHaveLength(1));
    fireEvent.change(input, { target: { value: "5900000000002" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalledTimes(2));

    await act(async () => releaseFirst?.());

    // A second POST would be refused: the row exists by then.
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(surpluses).toHaveLength(1);
    expect(patches[0]).toMatchObject({
      lineId: "sti-jam",
      body: { counted_quantity: 2 },
    });
  });

  it("says the search failed instead of showing an empty result", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const input = await renderPage();

    fireEvent.change(input, { target: { value: "mi" } });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The search failed",
    );
  });
});
