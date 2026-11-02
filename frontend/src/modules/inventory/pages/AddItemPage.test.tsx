import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AddItemPage from "./AddItemPage";
import { vi } from "vitest";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import * as modulesCtx from "@/contexts/ModulesContext";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { Toaster } from "sonner";
import { useFormGuardStore } from "@/store/formGuardStore";
import { useScanStore } from "@/store/scanStore";
import { serveLocations } from "@/test/serveLocations";

import { signInWith } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["items:write"]);
});

// Mock API
vi.mock("../lib/api", () => ({
  itemsApi: {
    create: vi.fn(),
  },
  labelsApi: {
    assign: vi.fn(),
  },
  storagesApi: {
    getAll: vi
      .fn()
      .mockResolvedValue([{ id: "1", name: "Fridge", parent_id: null }]),
  },
  categoriesApi: {
    getAll: vi.fn().mockResolvedValue([]),
  },
  storageTypesApi: {
    getAll: vi.fn().mockResolvedValue([]),
  },
  organizationsApi: {
    getMe: vi.fn().mockResolvedValue({}),
  },
  visionApi: {
    extract: vi.fn(),
  },
  uomsApi: {
    getAll: vi.fn().mockResolvedValue([]),
  },
}));

// jsdom has no canvas, so the real compressor never settles and a photo
// read here would wait forever rather than reach the reading.
vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
  prepareImageUpload: (file: File) => Promise.resolve(file),
}));

// Mock i18n
const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

/** The context as the page sees it, with *enabled* switched on or off. */
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

describe("AddItemPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    // The photo tab belongs to the `vision` module; these tests are about the
    // tabs, so they describe an installation that has it.
    withModules(["core", "items", "vision"]);
  });

  it("should render add item form with Vision and Manual tabs", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    // The title lives in the module shell header now, not in the page — the
    // page used to paint a second one under the list's header.
    // Both tabs should be present
    expect(
      await screen.findByRole("tab", { name: /Vision AI/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("tab", { name: /Manual/i }),
    ).toBeInTheDocument();
  });

  it("opens on the form, without switching tabs first", async () => {
    // 's criterion is "the item name field is visible on arrival".
    // Clicking Manual first would have passed against the Vision-first default
    // this replaced, so the click is gone from the test.
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByLabelText(/Product name/i)).toBeInTheDocument();
  });

  it("arms the nav-leave guard once something is typed, and disarms on the way out", async () => {
    // The same navigation click that the asset form answers with a
    // confirmation used to walk out of this form in silence.
    // The page's half of that contract is the store: dirty while the form
    // differs from what it opened with, null again on unmount.
    const user = userEvent.setup();
    const { unmount } = render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    await user.type(
      await screen.findByLabelText(/Product name/i),
      "Cast iron pan",
    );

    expect(useFormGuardStore.getState().dirtyForm).toBe("The product form");

    unmount();
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();
  });

  it("returns to the product list when Cancel is clicked after entering by address", async () => {
    // Entered from the list, the old `navigate(-1)` happened to land right;
    // entered by address (or from a notification after another module), it
    // popped to whatever came before in history — in the walkthrough,
    // /equipment/assets. Cancel promises the end of this task, so it names
    // the list itself rather than trusting the history stack.
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/inventory/items/add"]}>
            <ModulesProvider>
              <Routes>
                <Route path="/inventory/items/add" element={<AddItemPage />} />
                <Route
                  path="/inventory/items"
                  element={<div>Product list</div>}
                />
              </Routes>
            </ModulesProvider>
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await user.click(await screen.findByRole("button", { name: /^Cancel$/i }));

    expect(await screen.findByText("Product list")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Product name/i)).not.toBeInTheDocument();
  });

  it("does not hold on to a scanned place that is gone", async () => {
    // The scanner remembers the location it was pointed at, and this page
    // passed that memory on as if the address had asked for it: a place
    // asked for is not checked, so a deleted one sat in the field behind its
    // placeholder and the product could be saved into nothing.
    serveLocations([
      { id: "loc-a", name: "Shelf A" },
      { id: "loc-b", name: "Shelf B" },
    ]);
    useScanStore.setState({
      storageContext: { id: "loc-gone", name: "Gone", icon: "Box" },
    });

    try {
      render(
        <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <ModulesProvider>
                <Toaster />
                <AddItemPage />
              </ModulesProvider>
            </BrowserRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

      const name = await screen.findByRole("textbox", {
        name: /Product name/i,
      });
      await waitFor(() => expect(queryClient.isFetching()).toBe(0));
      fireEvent.change(name, { target: { value: "Tissues" } });
      // Named, and with no place left in the field: not saveable yet.
      await waitFor(() => {
        expect(queryClient.isFetching()).toBe(0);
        expect(
          screen.getByRole("button", { name: /Add Product/i }),
        ).toBeDisabled();
      });
      expect(screen.queryByText(/no longer on the list/i)).toBeNull();
    } finally {
      act(() => useScanStore.setState({ storageContext: null }));
    }
  });

  it("should have disabled submit button when form is empty", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    // Switch to manual tab
    const manualTab = await screen.findByRole("tab", { name: /Manual/i });
    await userEvent.click(manualTab);

    // Button disabled until name + storage are filled
    const submitButton = await screen.findByRole("button", {
      name: /Add Product/i,
    });
    expect(submitButton).toBeInTheDocument();
    expect(submitButton).toBeDisabled();
  });
  it("states the missing storage in a sentence, not in an i18next error", async () => {
    // `t("items:empty")` resolved to the namespace node, so the screen showed
    // i18next's own "returned an object instead of string" line — on a phone
    // it was the only text on the page.
    server.use(
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText(/No locations yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create location/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/returned an object/i)).toBeNull();
  });

  it("keeps the form on screen when every location belongs to a module", async () => {
    // The page used to be replaced whole by a panel whose only way out was
    // the settings screen — the module's main write path ended in a dead
    // end. The form stays, and the note under the storage field carries the
    // way out that works: create a location. The module-data switch is not
    // offered — this is a stock flow, which keeps a module's places out
    // whatever that switch says, so the reader would be sent to a dead end.
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage([]));
        return HttpResponse.json(
          onePage([
            {
              id: "loc-eq",
              name: "IT Storage",
              parent_id: null,
              context_tag: "equipment",
            },
          ]),
        );
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByLabelText(/Product name/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /create location/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open settings/i }),
    ).not.toBeInTheDocument();
  });
});

describe("AddItemPage — a label reading that found nothing", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    withModules(["core", "items", "vision"]);
    // An organization whose image reading runs, so the camera is offered.
    server.use(
      http.get("/api/v1/ai-connections/purposes", () =>
        HttpResponse.json(
          onePage([
            { key: "vision.extract", bound_connection_id: "c1", usable: true },
          ]),
        ),
      ),
    );
    // The camera opens through a file input the tab creates and clicks;
    // jsdom has no camera, so the click hands back one photo instead.
    const label = new File(["x"], "label.jpg", { type: "image/jpeg" });
    const realClick = HTMLInputElement.prototype.click;
    vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(function (
      this: HTMLInputElement,
    ) {
      if (this.type !== "file") return realClick.call(this);
      fireEvent.change(this, { target: { files: [label] } });
    });
  });

  afterEach(() => vi.restoreAllMocks());

  it("says nothing could be read, and offers a new photo or the form", async () => {
    // Measured on production: a blurry photo answers 200 with every field
    // null — and, with the nutrition module on, a group of nulls under
    // `extra`. The screen stayed on the photo without a word, and the reader
    // could not tell a failed reading from a slow one.
    server.use(
      http.post("/api/v1/vision/extract", () =>
        HttpResponse.json({
          name: null,
          weight: null,
          expiry_date: null,
          production_date: null,
          brand: null,
          category: null,
          barcode: null,
          weight_value: null,
          weight_uom: null,
          volume_value: null,
          volume_uom: null,
          extra: { nutrition: { energy_kcal: null, ingredients: null } },
          resolved: null,
        }),
      ),
    );
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await user.click(await screen.findByRole("tab", { name: /Vision AI/i }));
    const camera = screen.getByRole("button", { name: /take product photo/i });
    await waitFor(() => expect(camera).toBeEnabled());
    await user.click(camera);
    await user.click(
      await screen.findByRole("button", { name: /analyze label \(1\)/i }),
    );

    expect(
      await screen.findByText(/nothing could be read from this photo/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /retake photo/i }),
    ).toBeInTheDocument();
    // An empty answer is not a filled-in form: nothing arms the leave guard.
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    await user.click(screen.getByRole("button", { name: /enter by hand/i }));

    expect(await screen.findByLabelText(/Product name/i)).toHaveValue("");
  });

  it("takes a reading without a name to the form, and says what it filled in", async () => {
    // A brand and an expiry date but no name: the reading was merged into a
    // form hidden behind the camera tab, and the screen stayed on the photo
    // without a word.
    server.use(
      http.post("/api/v1/vision/extract", () =>
        HttpResponse.json({
          name: null,
          weight: null,
          expiry_date: "2026-12-01",
          production_date: null,
          brand: "Mlekovita",
          category: null,
          barcode: null,
          weight_value: null,
          weight_uom: null,
          volume_value: null,
          volume_uom: null,
          extra: { nutrition: { energy_kcal: null, ingredients: null } },
          resolved: null,
        }),
      ),
    );
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
              <Toaster />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await user.click(await screen.findByRole("tab", { name: /Vision AI/i }));
    const camera = screen.getByRole("button", { name: /take product photo/i });
    await waitFor(() => expect(camera).toBeEnabled());
    await user.click(camera);
    await user.click(
      await screen.findByRole("button", { name: /analyze label \(1\)/i }),
    );

    expect(
      await screen.findByText(
        "Read from the photo and put in the form: brand, expiry date. The name could not be read — type it in.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText(/Product name/i)).toHaveValue("");
    expect(
      screen.queryByText(/nothing could be read/i),
    ).not.toBeInTheDocument();
  });
});

describe("AddItemPage without the photo module", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    withModules(["core", "items"]);
  });

  it("offers the form alone, with no tab that cannot work", async () => {
    // `vision` can be switched off, and the request behind the tab then comes
    // back refused. One entrance is clearer than two when one is shut.
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByLabelText(/Product name/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
  });

  it("says the locations did not load instead of offering an empty required picker", async () => {
    // The "you have no storages" guard tested `storages.length === 0`, and a
    // failed request leaves `storages` undefined — so the form rendered whole,
    // with a required picker holding nothing and no word about why.
    server.use(
      http.get(
        "/api/v1/locations",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Product name/i)).not.toBeInTheDocument();
  });
  it("answers a read-only account with the notice, not with the form", async () => {
    // The list that leads here already asks. This route did not, so an
    // account holding only `items:read` filled the whole form in and met a
    // 403 at the end of it.
    signInWith(["items:read"]);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ModulesProvider>
              <AddItemPage />
            </ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByRole("note")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Product name/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: /Manual/i }),
    ).not.toBeInTheDocument();
  });
});
