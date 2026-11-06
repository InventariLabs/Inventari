import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import ScanPage from "./ScanPage";
import { useAuthStore } from "@/store/authStore";
import { labelsApi } from "@/lib/api/labels";
import { itemsApi } from "@/lib/api/items";
import { useScanStore } from "@/store/scanStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

const navigateMock = vi.fn();

// Mock react-router-dom's useNavigate so navigation is observable without a
// router state probe.
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

// Mock ModulesContext so ScanPage doesn't require ModulesProvider in tests
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: [],
    isModuleEnabled: () => false,
  }),
  // QuickAddModal reaches this through useItemForm; without it the untagged
  // label case renders against a provider that is not mounted here.
  useEnabledModulesOptional: () => [],
}));

// Mock API
vi.mock("../lib/api", () => ({
  visionApi: {
    extract: vi.fn(),
  },
  storagesApi: {
    getAll: vi.fn().mockResolvedValue([
      {
        id: "1",
        name: "Kitchen Fridge",
        location_type: {
          name: "Fridge",
          type_code: "FRIDGE",
          icon: "Snowflake",
        },
      },
    ]),
  },
  labelsApi: {
    scan: vi.fn(),
  },
  itemsApi: {
    consume: vi.fn(),
    updateQuantity: vi.fn(),
  },
}));

// The component scans through this module — the mock above covers a
// different path and never sees the component's calls.
vi.mock("@/lib/api/labels", () => ({
  labelsApi: {
    scan: vi.fn(),
  },
}));

// The scan sheet consumes through this module, which the relative mock above
// never sees. Everything else stays real; only the consume call is
// observable here.
vi.mock("@/lib/api/items", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/items")>();
  return {
    ...actual,
    itemsApi: { ...actual.itemsApi, consume: vi.fn() },
  };
});

// Mock html5-qrcode
vi.mock("html5-qrcode", () => {
  // A class on purpose: the hook constructs this with `new`, and vitest 5
  // refuses a mock built from an arrow implementation — the construction
  // throws into the hook's catch and prints "Camera start error:".
  class MockHtml5Qrcode {
    isScanning = true;
    start() {
      return Promise.resolve();
    }
    stop() {
      return Promise.resolve();
    }
    pause() {
      return Promise.resolve();
    }
    resume() {
      return Promise.resolve();
    }
    clear() {}
  }
  return {
    Html5Qrcode: MockHtml5Qrcode,
    Html5QrcodeSupportedFormats: {
      QR_CODE: 0,
      EAN_13: 1,
      EAN_8: 2,
      UPC_A: 3,
      UPC_E: 4,
      CODE_128: 5,
      CODE_39: 6,
    },
  };
});

describe("ScanPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    navigateMock.mockReset();
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        // The scanner's sheets are gated on these two; without them the
        // suite would be exercising the read-only screen throughout.
        permissions: ["items:write", "shopping_lists:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });

    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
  });

  it("should start camera automatically on mount", async () => {
    // Mock mobile device
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query.includes("coarse"), // simulate touch support
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ScanPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    // Should see the qr-reader div after loading
    await waitFor(() => {
      const reader = document.getElementById("qr-reader");
      expect(reader).toBeInTheDocument();
    });

    // Should see the instruction text
    const instruction = await screen.findByTestId("scan-instructions");
    expect(instruction).toBeInTheDocument();
  });

  it("goes home from the scanner opened by address, where there is no back", async () => {
    // A bare address or a fresh tab makes the scanner the first entry of its
    // history, and navigate(-1) from there does nothing.
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/inventory/scan"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /back/i }));

    expect(navigateMock).toHaveBeenCalledWith("/", { replace: true });
  });

  it("goes home from the scanner a redirect replaced into place, where the key is no longer the initial one", async () => {
    // A printed code's address (/s/<code>) and the sign-in return replace the
    // first entry: the location gets a fresh key but nothing was added to the
    // history, and the router's own counter says there is nothing to pop.
    window.history.replaceState({ idx: 0 }, "");
    try {
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[{ pathname: "/inventory/scan", key: "replaced" }]}
          >
            <ScanPage />
          </MemoryRouter>
        </QueryClientProvider>,
      );

      await userEvent.click(
        await screen.findByRole("button", { name: /back/i }),
      );

      expect(navigateMock).toHaveBeenCalledWith("/", { replace: true });
    } finally {
      window.history.replaceState(null, "");
    }
  });

  it("still goes back to where the reader came from inside the app", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={["/inventory", "/inventory/scan"]}
          initialIndex={1}
        >
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /back/i }));

    expect(navigateMock).toHaveBeenCalledWith(-1);
  });

  it("pins the scanner between the app bar and the bottom nav instead of subtracting a fixed offset", async () => {
    // The shell above the scanner changes height with orientation; a
    // calc(100dvh - Nrem) height pushed the camera area and aim frame
    // below a landscape phone's viewport.
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ScanPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );
    await screen.findByTestId("scan-instructions");
    const root = container.querySelector("div > div") as HTMLElement | null;
    expect(root).toHaveClass("fixed", "top-14");
    expect(root?.className).not.toContain("100dvh-7.5rem");
  });

  it("constructs the mocked camera the way the hook does", async () => {
    // The hook builds the scanner with `new`, so the mock has to be
    // constructible: vitest 5 throws "is not a constructor" on an arrow
    // implementation, the hook catches it and prints "Camera start error:".
    // In a full run that print only lands inside whichever test crosses the
    // 500 ms camera start — a flake by timing. Constructing it here makes
    // the break immediate and named.
    const { Html5Qrcode } = await import("html5-qrcode");
    const scanner = new Html5Qrcode("qr-reader");
    expect((scanner as { isScanning: boolean }).isScanning).toBe(true);
  });

  it("opens a scanned document, continuing DRAFTs straight into the edit form", async () => {
    // The camera is idle in tests; the manual-input field still drives the
    // same handler through the URL ?code= param, so scan is triggered via
    // the labels API mock and the search param path.
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/001",
      message_key: "scan:result.document",
      message_params: { number: "IN/2026/001" },
      action: "open_document",
      document: {
        id: "doc-1",
        number: "IN/2026/001",
        status: "DRAFT",
        type: "IN",
      },
      document_mode: "continue",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=IN%2F2026%2F001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(labelsApi.scan).toHaveBeenCalledWith("IN/2026/001");
    });
    // An in-progress document opens in continuation (edit form).
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith(
        "/warehouse/documents/doc-1#edit",
      );
    });
  });

  it("opens a finished document as a preview", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/001",
      message_key: "scan:result.document",
      message_params: { number: "IN/2026/001" },
      action: "open_document",
      document: {
        id: "doc-1",
        number: "IN/2026/001",
        status: "COMPLETED",
        type: "IN",
      },
      document_mode: "preview",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=IN%2F2026%2F001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/warehouse/documents/doc-1");
    });
  });

  it("opens a CONFIRMED document into the floor flow", async () => {
    // A printout of a confirmed IN document is a receiving list in hand
    // — the scan must open the receiving session, not a passive preview.
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/001",
      message_key: "scan:result.document",
      message_params: { number: "IN/2026/001" },
      action: "open_document",
      document: {
        id: "doc-1",
        number: "IN/2026/001",
        status: "CONFIRMED",
        type: "IN",
      },
      document_mode: "execute",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=IN%2F2026%2F001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith(
        "/warehouse/documents/doc-1#receive",
      );
    });
  });

  // The label carries its own purpose. Before this, nothing ever stamped one
  // on a generated label and the page fell back to a scan-mode strip that
  // never rendered — so a blank sticker could only ever open the product
  // form, whatever it had been printed for.
  it("sends a blank label printed for assets to the equipment form", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "unassigned",
      label_code: "EQP-0001",
      message_key: "scan:result.labelReady",
      action: "show_quick_add",
      context_tag: "equipment",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=EQP-0001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/equipment/add", {
        state: { labelCode: "EQP-0001", template: undefined },
      });
    });
  });

  it("shows what is on a scanned location, and sets the scan context only on request", async () => {
    server.use(
      http.get("/api/v1/stock-quants", () =>
        HttpResponse.json({
          items: [
            {
              id: "q1",
              product_template_id: "p1",
              location_id: "shelf",
              quantity: "3.000",
              reserved_quantity: "0",
              available_quantity: "3.000",
              product_name: "Rye flour",
              uom_symbol: "kg",
              location_name: "Shelf 2",
            },
          ],
          total: 1,
          offset: 0,
          limit: 100,
        }),
      ),
    );
    useScanStore.setState({ storageContext: null });
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "storage_context",
      label_code: "LOC-7",
      action: "set_storage_context",
      location: { id: "rack", name: "Rack", icon: "📦" },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=LOC-7"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Rye flour")).toBeInTheDocument();
    expect(useScanStore.getState().storageContext).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: "Use as scan context" }),
    );

    expect(useScanStore.getState().storageContext?.id).toBe("rack");
  });

  it("keeps an untagged blank label on the product form", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "unassigned",
      label_code: "STM-0001",
      message_key: "scan:result.labelReady",
      action: "show_quick_add",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=STM-0001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(labelsApi.scan).toHaveBeenCalledWith("STM-0001");
    });
    expect(navigateMock).not.toHaveBeenCalledWith(
      "/equipment/add",
      expect.anything(),
    );
  });

  /**
   * The sheet's primary button says "Remove 1 (first to expire)" and used to take the whole
   * record that expires first — two kilograms of beef gone after one click.
   * The per-location "−" beside it takes one. Reverting the fix makes the
   * assertion below expect quantity 2 and fail.
   */
  it("takes one unit from the first-expiring record when the button says Remove 1 (first to expire)", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "product_stock",
      label_code: "STM-0001",
      message_key: "scan:result.product",
      message_params: { product: "Beef" },
      action: "show_stock_actions",
      stock_summary: {
        total_quantity: 4,
        unit: "kg",
        items: [
          {
            id: "item-first",
            expiry_date: "2026-10-01",
            location: "Fridge",
            quantity: 2,
          },
          {
            id: "item-second",
            expiry_date: "2027-01-01",
            location: "Freezer",
            quantity: 2,
          },
        ],
      },
    });
    vi.mocked(itemsApi.consume).mockResolvedValue({
      id: "item-first",
      quantity: "1",
      is_deleted: false,
    } as Awaited<ReturnType<typeof itemsApi.consume>>);

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=STM-0001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const consumeButton = await screen.findByRole("button", {
      name: "Remove 1 (first to expire)",
    });
    await userEvent.click(consumeButton);

    await waitFor(() => {
      expect(itemsApi.consume).toHaveBeenCalledWith("item-first", 1);
    });
  });

  /**
   * A record's free figure depends on the hold it shares with its siblings,
   * so a quantity change reads the label again instead of patching one number.
   * Without the rescan the row keeps saying "4 reserved, 1 available" after
   * the quantity went up.
   */
  it("shows the reserved and available figures the server returns after adding one", async () => {
    const sheet = (quantity: number, available: number) => ({
      status: "product_stock" as const,
      label_code: "STM-0002",
      message_key: "scan:result.product",
      message_params: { product: "Beef" },
      action: "show_stock_actions" as const,
      stock_summary: {
        total_quantity: quantity,
        unit: "kg",
        items: [
          {
            id: "item-held",
            expiry_date: null,
            location: "Fridge",
            quantity,
            reserved_quantity: 4,
            available_quantity: available,
          },
        ],
      },
    });
    vi.mocked(labelsApi.scan)
      .mockResolvedValueOnce(sheet(5, 1))
      .mockResolvedValue(sheet(6, 2));
    vi.spyOn(itemsApi, "updateQuantity").mockResolvedValue({
      id: "item-held",
      quantity: "6",
      is_deleted: false,
    } as Awaited<ReturnType<typeof itemsApi.updateQuantity>>);

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=STM-0002"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("4 reserved, 1 available")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Add 1" }));

    expect(await screen.findByText("4 reserved, 2 available")).toBeTruthy();
  });
});

/**
 * The scanner reads for everybody; only what follows a scan is gated.
 *
 * `GET /labels/scan/{code}` asks for nothing beyond membership, so "what is
 * this thing" stays answerable. A blank label is the opposite case: its only
 * use is creating the record it will name, and opening that form for an
 * account that may not create one is the whole defect this screen had — the
 * refusal used to arrive after the form was filled in.
 */
describe("ScanPage — an account that may not change stock", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    navigateMock.mockReset();
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Reader",
        email: "reader@example.com",
        preferred_language: "en",
        role: "user",
        permissions: ["items:read"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("says why before the reader scans anything", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ScanPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
  });

  it("refuses a blank label instead of opening the product form", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "unassigned",
      label_code: "LB-0001",
      message_key: "scan:result.labelReady",
      action: "show_quick_add",
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?code=LB-0001"]}>
          <ScanPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(labelsApi.scan).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: /add/i }),
      ).not.toBeInTheDocument(),
    );
    expect(navigateMock).not.toHaveBeenCalledWith(
      "/equipment/add",
      expect.anything(),
    );
  });
});
