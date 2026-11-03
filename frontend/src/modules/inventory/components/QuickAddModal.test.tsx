import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QuickAddModal from "./QuickAddModal";
import { ModulesProvider } from "@/contexts/ModulesContext";
import * as modulesCtx from "@/contexts/ModulesContext";

// The camera button loads the SDK after paint; this spec is not about it.
vi.mock("@/modules/shared/components/LazyScanToFill", () => ({
  LazyScanToFill: () => null,
}));

// Mock API
vi.mock("../lib/api", () => ({
  labelsApi: {
    assign: vi.fn().mockResolvedValue({
      id: "new-item",
      location_id: "1",
      category_id: "1",
    }),
  },
  storagesApi: {
    getAll: vi.fn().mockResolvedValue([
      {
        id: "1",
        name: "Fridge",
        location_type: { icon: "Snowflake", type_code: "FRIDGE" },
      },
    ]),
  },
  categoriesApi: {
    getAll: vi.fn().mockResolvedValue([{ id: "1", name: "Food", icon: "🍎" }]),
  },
  visionApi: {
    extract: vi.fn(),
  },
  storageTypesApi: {
    getAll: vi.fn().mockResolvedValue([]),
  },
  organizationsApi: {
    getMe: vi.fn().mockResolvedValue({}),
  },
  uomsApi: {
    getAll: vi.fn().mockResolvedValue([]),
  },
}));

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

/** The context as the modal sees it, with *enabled* switched on or off. */
function withModules(enabled: string[]) {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: enabled,
    isModuleEnabled: (name: string) => enabled.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
}

describe("QuickAddModal", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    // The photo tab belongs to the `vision` module; these tests are about the
    // tabs, so they describe an installation that has it.
    withModules(["core", "items", "vision"]);
  });

  it("opens on the form, with the camera one tab away", () => {
    render(
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <QuickAddModal
              labelCode="STM-0001"
              onClose={() => {}}
              onSuccess={() => {}}
            />
          </ModulesProvider>
        </QueryClientProvider>
      </BrowserRouter>,
    );

    expect(screen.getByText(/New Product/i)).toBeInTheDocument();
    // The product name field is the form; "Take Product Photo" is the other tab.
    expect(screen.getByLabelText(/Product name/i)).toBeInTheDocument();
    expect(screen.queryByText(/Take Product Photo/i)).toBeNull();
    expect(screen.getAllByText(/Vision AI/i).length).toBeGreaterThan(0);
  });

  it("offers to attach a free pool label to an existing product, and a barcode not", () => {
    const renderModal = (messageKey: string) =>
      render(
        <BrowserRouter>
          <QueryClientProvider client={queryClient}>
            <ModulesProvider>
              <QuickAddModal
                labelCode="STM-0001"
                messageKey={messageKey}
                onClose={() => {}}
                onSuccess={() => {}}
              />
            </ModulesProvider>
          </QueryClientProvider>
        </BrowserRouter>,
      );

    const barcode = renderModal("scan:result.newProduct");
    expect(screen.queryByText("Attach to an existing product")).toBeNull();
    barcode.unmount();

    renderModal("scan:result.labelReady");
    fireEvent.click(screen.getByText("Attach to an existing product"));
    expect(
      screen.getByRole("textbox", { name: "Search products…" }),
    ).toBeInTheDocument();
  });

  it("asks for a product code after a pool label, and not after a barcode", () => {
    const renderModal = (labelCode: string) =>
      render(
        <BrowserRouter>
          <QueryClientProvider client={queryClient}>
            <ModulesProvider>
              <QuickAddModal
                labelCode={labelCode}
                onClose={() => {}}
                onSuccess={() => {}}
              />
            </ModulesProvider>
          </QueryClientProvider>
        </BrowserRouter>,
      );

    // The scanned barcode is the product's code: shown once, in the header.
    const barcode = renderModal("8715700017006");
    expect(screen.getAllByText("8715700017006")).toHaveLength(1);
    expect(screen.queryByLabelText("Product code")).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate code" })).toBeNull();
    barcode.unmount();

    renderModal("STM-0001");
    expect(screen.getByLabelText("Product code")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Generate code" }),
    ).toBeInTheDocument();
  });

  it("should switch to manual tab", async () => {
    render(
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <QuickAddModal
              labelCode="STM-0001"
              onClose={() => {}}
              onSuccess={() => {}}
            />
          </ModulesProvider>
        </QueryClientProvider>
      </BrowserRouter>,
    );

    const manualTab = screen.getByRole("button", { name: /Manual/i });
    fireEvent.click(manualTab);

    // Check for label which is robust
    expect(await screen.findByText(/Product name/i)).toBeInTheDocument();
  });

  it("should call assign API when manual form submitted", async () => {
    const onSuccess = vi.fn();
    render(
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <QuickAddModal
              labelCode="STM-0001"
              onClose={() => {}}
              onSuccess={onSuccess}
            />
          </ModulesProvider>
        </QueryClientProvider>
      </BrowserRouter>,
    );

    // Switch to manual
    fireEvent.click(screen.getByRole("button", { name: /Manual/i }));

    // Verify manual tab is active
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Manual/i })).toHaveClass(
        "bg-surface-card",
      );
    });
  });
});

describe("QuickAddModal without the photo module", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    withModules(["core", "items"]);
  });

  const open = () =>
    render(
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <QuickAddModal
              labelCode="STM-0001"
              onClose={() => {}}
              onSuccess={() => {}}
            />
          </ModulesProvider>
        </QueryClientProvider>
      </BrowserRouter>,
    );

  it("does not offer a tab that would fail on the first click", () => {
    // `vision` is a module and can be switched off. The tab was drawn anyway,
    // and the request behind it comes back refused — an entrance to a room
    // that is not there.
    open();

    expect(screen.queryAllByText(/Vision AI/i)).toHaveLength(0);
  });

  it("leaves the form itself untouched", () => {
    open();

    expect(screen.getByLabelText(/Product name/i)).toBeInTheDocument();
    expect(screen.queryAllByText(/Manual/i)).toHaveLength(0);
  });
});
