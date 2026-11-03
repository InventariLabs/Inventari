import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { useQuickAdd } from "./useQuickAdd";
import { server } from "@/test/mocks/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { visionApi } from "@/lib/api/vision";
import { useScanStore } from "@/store/scanStore";
import { useFormMemoryStore } from "@/store/formMemoryStore";
import { useFormGuardStore } from "@/store/formGuardStore";
import { toast } from "sonner";
import i18next from "i18next";
import type { VisionExtractResult } from "@/types";
import { onePage } from "@/test/mocks/page";
import { serveLocations } from "@/test/serveLocations";

// jsdom has no canvas, so the real compressor never settles and the vision
// tests below would time out rather than fail.
vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
  prepareImageUpload: (file: File) => Promise.resolve(file),
}));

vi.mock("@/lib/api/vision", () => ({
  visionApi: { extract: vi.fn(), extractNutrition: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>{children}</ModulesProvider>
    </QueryClientProvider>
  );
};

describe("useQuickAdd", () => {
  it("initializes with the manual tab active", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: mockOnSuccess }),
      { wrapper: createWrapper() },
    );

    expect(result.current.activeTab).toBe("manual");
  });

  it("exposes tab switching", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: mockOnSuccess }),
      { wrapper: createWrapper() },
    );

    expect(typeof result.current.setActiveTab).toBe("function");
    expect(["vision", "manual"]).toContain(result.current.activeTab);
  });

  it("exposes form data management", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: mockOnSuccess }),
      { wrapper: createWrapper() },
    );

    expect(result.current).toHaveProperty("formData");
    expect(result.current).toHaveProperty("setFormData");
    expect(result.current).toHaveProperty("errors");
    expect(result.current).toHaveProperty("setErrors");
  });

  it("arms the nav-leave guard while the form holds unsaved work", () => {
    // Both consumers of this hook — the add-product page and QuickAddModal —
    // sit in front of the same gate; the registration belongs here, once,
    // not at each mounting site. Measured live: the command palette
    // navigates over an open modal, so a dirty quick-add must be registered
    // or the palette walks out of it without a question.
    useFormGuardStore.getState().setDirtyForm(null);

    const { result, unmount } = renderHook(
      () => useQuickAdd({ onSuccess: vi.fn() }),
      { wrapper: createWrapper() },
    );

    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    act(() => {
      result.current.setFormData((prev) => ({ ...prev, name: "Jam" }));
    });

    expect(useFormGuardStore.getState().dirtyForm).toBe("The product form");

    unmount();
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();
  });

  it("exposes submit function", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: mockOnSuccess }),
      { wrapper: createWrapper() },
    );

    expect(typeof result.current.submit).toBe("function");
  });

  it("exposes mutation objects", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: mockOnSuccess }),
      { wrapper: createWrapper() },
    );

    expect(result.current).toHaveProperty("assignMutation");
  });

  it("handles optional parameters", () => {
    const mockOnSuccess = vi.fn();

    const { result } = renderHook(
      () =>
        useQuickAdd({
          labelCode: "test-label",
          initialStorageId: "storage-1",
          onSuccess: mockOnSuccess,
        }),
      { wrapper: createWrapper() },
    );

    expect(result.current.activeTab).toBe("manual");
    expect(typeof result.current.submit).toBe("function");
  });

  it("sends the chosen photo once the item exists", async () => {
    // Picking a file produced a preview and nothing else: the image never
    // left the browser. A test that only checks the callback is a function
    // would not have noticed.
    const uploads: string[] = [];
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json(
          { id: "new-item", name: "Jam", quantity: 1, metadata: null },
          { status: 201 },
        ),
      ),
      http.post("/api/v1/items/:id/image", ({ params }) => {
        uploads.push(String(params.id));
        return HttpResponse.json({ image_url: "/uploads/jam.jpg" });
      }),
    );

    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.handleImageSelect(
        new File(["photo"], "jam.jpg", { type: "image/jpeg" }),
      );
      result.current.setFormData((prev) => ({
        ...prev,
        name: "Jam",
        quantity: "1",
        location_id: "1",
      }));
    });

    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(uploads).toEqual(["new-item"]));
  });

  it("does not say the product was not saved when only its photo was refused by an ended session", async () => {
    // The product is created first; the photo goes up after. A session that
    // ends in between used to put "this was not saved" in a toast beside
    // "Product added".
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json(
          { id: "new-item", name: "Jam", quantity: 1, metadata: null },
          { status: 201 },
        ),
      ),
      http.post("/api/v1/items/:id/image", () =>
        HttpResponse.json({ detail: "expired" }, { status: 401 }),
      ),
      http.post(
        "*/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const error = vi.spyOn(toast, "error");

    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });
    act(() => {
      result.current.handleImageSelect(
        new File(["photo"], "jam.jpg", { type: "image/jpeg" }),
      );
      result.current.setFormData((prev) => ({
        ...prev,
        name: "Jam",
        quantity: "1",
        location_id: "1",
      }));
    });
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(error).toHaveBeenCalled());
    const shown = error.mock.calls.map(([message]) => String(message));
    expect(shown).toContain(i18next.t("items:messages.fileUploadFailed"));
    expect(shown).not.toContain(i18next.t("common:errors.sessionEnded"));
    error.mockRestore();
  });
});

/**
 * The picker used to read the full list while the products list underneath it
 * read the scoped one, so the form handed out locations the list then called
 * "Unknown". It now offers what the general screens are about — and keeps
 * whatever the form arrived holding, so a record already put away in a
 * module's location can still be opened.
 */
describe("useQuickAdd — which locations the form offers", () => {
  const shelf = { id: "loc-shelf", name: "Shelf A" };
  const rack = {
    id: "loc-equipment",
    name: "Server Rack B",
    context_tag: "equipment",
  };

  /**
   * The organization's locations, as the stock flow's ask sees them: the
   * endpoint leaves a module's places out when the request excludes them
   * (which every stock-flow ask does), whatever the organization mixes into
   * its general lists.
   */
  function serveStorages(showModuleData: boolean, rows = [shelf, rack]) {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          settings: showModuleData ? { show_module_data: true } : {},
        }),
      ),
    );
    return serveLocations(rows);
  }

  /** The asks about what is on offer; naming a place by id is another ask. */
  const offers = (requests: URLSearchParams[]) =>
    requests.filter((r) => r.get("usage") !== "all");

  const open = (options: { initialStorageId?: string } = {}) =>
    renderHook(() => useQuickAdd({ onSuccess: vi.fn(), ...options }), {
      wrapper: createWrapper(),
    });

  it("leaves out what the organization keeps out of the general lists", async () => {
    const requests = serveStorages(false);

    const { result } = open();

    // The one place on offer is put in the field; the rack is not.
    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-shelf"),
    );
    expect(result.current.noStorages).toBe(false);
    expect(offers(requests).length).toBeGreaterThan(0);
    expect(
      offers(requests).every(
        (r) => r.get("exclude_module_contexts") === "true",
      ),
    ).toBe(true);
  });

  it("keeps a module's places out even when the organization mixes its lists", async () => {
    // The form is a stock flow: what it offers is what may hold stock, and
    // what the general lists mix says nothing about where a product is filed.
    const requests = serveStorages(true);

    const { result } = open();

    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-shelf"),
    );
    expect(offers(requests).length).toBeGreaterThan(0);
    expect(
      offers(requests).every(
        (r) => r.get("exclude_module_contexts") === "true",
      ),
    ).toBe(true);
  });

  it("asks the endpoint what is on offer, and never reads the catalogue", async () => {
    const requests = serveStorages(false);

    const { result } = open();

    await waitFor(() => expect(result.current.noStorages).toBe(false));
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every((r) => Number(r.get("limit")) <= 100)).toBe(true);
    expect(requests.every((r) => r.get("counts") === "false")).toBe(true);
  });

  it("puts the single location it is offered into the field", async () => {
    serveStorages(true);

    const { result } = open();

    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-shelf"),
    );
    // A choice nobody made is not an unsaved change: the leave guard must
    // stay quiet over a form the reader never touched.
    expect(result.current.isDirty).toBe(false);
  });

  it("keeps the location it was opened on, whatever owns it", async () => {
    serveStorages(false);

    const { result } = open({ initialStorageId: "loc-equipment" });

    await waitFor(() => expect(result.current.noStorages).toBe(false));
    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-equipment"),
    );
    // Given time to be cleared, were it judged not on offer: a place the form
    // arrived holding is offered whatever the stock scope says.
    await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
    expect(result.current.formData.location_id).toBe("loc-equipment");
  });

  it("does not hold a location the picker cannot show", async () => {
    // The remembered id survives a reload and a profile switch, and comes
    // back from localStorage whether or not the location still exists. Seeded
    // anyway it produced the state that has no way out: the field on its
    // placeholder, the shortcut beside it linking to "Storage not found", and
    // the product saveable into a location the form cannot name.
    //
    // The picker here offers nothing at all, so there is no eligible
    // location to fall back on either: with one to offer, the field takes
    // that one instead (the test below), and the dead id never surfaces
    // in either case.
    serveStorages(false, []);
    act(() => {
      useScanStore.setState({ lastStorageId: "loc-deleted" });
    });

    const { result } = open();

    await waitFor(() => expect(result.current.noStorages).toBe(true));
    await waitFor(() => expect(result.current.formData.location_id).toBe(""));

    act(() => result.current.submit());
    await waitFor(() => expect(result.current.errors.location_id).toBeTruthy());

    act(() => {
      useScanStore.setState({ lastStorageId: null });
    });
  });

  describe("what the reader is told about a place that is gone", () => {
    const shelf2 = { id: "loc-shelf-2", name: "Shelf B" };
    const placeSentence =
      "This location is no longer on the list — choose one of the available locations";

    afterEach(() => {
      vi.restoreAllMocks();
      act(() => {
        useScanStore.setState({ lastStorageId: null, storageContext: null });
      });
    });

    it("drops a remembered place without a word", async () => {
      // The first thing a returning demo visitor met after the nightly
      // reset: "this place is no longer on the list", about a place they had
      // not chosen and could not see. The sentence points at nothing.
      const info = vi.spyOn(toast, "info");
      serveStorages(false, [shelf, shelf2]);
      act(() => {
        useScanStore.setState({ lastStorageId: "loc-deleted" });
      });

      const { result } = open();

      await waitFor(() => expect(result.current.noStorages).toBe(false));
      await waitFor(() => expect(result.current.formData.location_id).toBe(""));
      expect(info).not.toHaveBeenCalled();
    });

    it("drops the scanner's remembered place without a word", async () => {
      // The same memory by another name: a location scanned on an earlier
      // visit, not a choice made in this form.
      const info = vi.spyOn(toast, "info");
      serveStorages(false, [shelf, shelf2]);
      act(() => {
        useScanStore.setState({
          storageContext: { id: "loc-deleted", name: "Gone", icon: "Box" },
        });
      });

      const { result } = open();

      await waitFor(() => expect(result.current.noStorages).toBe(false));
      await waitFor(() => expect(result.current.formData.location_id).toBe(""));
      expect(info).not.toHaveBeenCalled();
    });

    it("says so when the place the reader chose in this form is gone", async () => {
      const info = vi.spyOn(toast, "info");
      serveStorages(false, [shelf, shelf2]);

      const { result } = open();

      await waitFor(() => expect(result.current.noStorages).toBe(false));
      act(() => result.current.handleInputChange("location_id", "loc-deleted"));

      await waitFor(() => expect(info).toHaveBeenCalledWith(placeSentence));
      expect(result.current.formData.location_id).toBe("");
    });

    it("says so when a different place than the remembered one is gone", async () => {
      // Remembered and chosen differ: what the reader picked over the memory
      // is still their choice.
      const info = vi.spyOn(toast, "info");
      serveStorages(false, [shelf, shelf2]);
      act(() => {
        useScanStore.setState({ lastStorageId: "loc-shelf" });
      });

      const { result } = open();

      await waitFor(() =>
        expect(result.current.formData.location_id).toBe("loc-shelf"),
      );
      act(() => result.current.handleInputChange("location_id", "loc-deleted"));

      await waitFor(() => expect(info).toHaveBeenCalledWith(placeSentence));
    });
  });

  it("fills the single location once a remembered one is cleared", async () => {
    // The memory reaches back further than the offer does: the previous
    // product stood in an equipment rack, which this stock flow never
    // offers. `useMissingPicks` empties the field — and the one eligible
    // location is still the answer, so the field ends on it
    // rather than on its placeholder with a form that cannot be saved.
    serveStorages(true);
    act(() => {
      useScanStore.setState({ lastStorageId: "loc-equipment" });
    });

    const { result } = open();

    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-shelf"),
    );
    // Filling in what nobody chose is still nobody's unsaved change.
    expect(result.current.isDirty).toBe(false);

    act(() => {
      useScanStore.setState({ lastStorageId: null });
    });
  });

  it("marks a location it filled in from the previous product", async () => {
    serveStorages(false);
    act(() => {
      useScanStore.setState({ lastStorageId: "loc-shelf" });
    });

    const { result } = open();

    await waitFor(() =>
      expect(result.current.formData.location_id).toBe("loc-shelf"),
    );
    expect(result.current.carriedOver.storage).toBe(true);

    act(() => result.current.clearCarriedOver());
    await waitFor(() => expect(result.current.formData.location_id).toBe(""));
    expect(result.current.carriedOver.storage).toBe(false);

    act(() => {
      useScanStore.setState({ lastStorageId: null });
    });
  });
});

/**
 * An empty picker has two causes and they need different answers: nothing has
 * been created yet, or locations exist but belong to a module this workspace
 * keeps out of its general lists. Told the first when the second is true, the
 * reader goes and creates a duplicate of a location that is already there.
 *
 * A stock flow is never told the second: its own purpose keeps a module's
 * places out, so the switch would reveal nothing in this form.
 */
describe("useQuickAdd — why the picker is empty", () => {
  const rack = {
    id: "loc-equipment",
    name: "Server Rack B",
    context_tag: "equipment",
  };

  function serve(
    rows: Array<{ id: string; name: string; context_tag?: string }>,
  ) {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ id: "org-1", name: "Test Org", settings: {} }),
      ),
    );
    serveLocations(rows);
  }

  const open = () =>
    renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });

  it("says nothing is hidden when there is nothing anywhere", async () => {
    serve([]);

    const { result } = open();

    await waitFor(() => expect(result.current.noStorages).toBe(true));
    expect(result.current.hasHiddenStorages).toBe(false);
  });

  it("never blames the module-data switch for a picker it empties itself", async () => {
    // The only location the organization has belongs to a module, and the
    // policy is off. The switch would reveal it in the general lists and
    // never in this form — the stock flow's own purpose keeps it out either
    // way — so the reader is told the truth that has a way out: there is no
    // location to put this in yet, and creating one is what helps.
    serve([rack]);

    const { result } = open();

    await waitFor(() => expect(result.current.noStorages).toBe(true));
    expect(result.current.hasHiddenStorages).toBe(false);
  });
});

/**
 * The picker used to read the full catalogue while the products list
 * underneath it read the scoped one, so the form handed out categories the
 * list then hid — and a category owned by a module moves the record into
 * that module on the way past, silently. It now offers the same set the list
 * shows, keeps whatever the record deliberately carries, and refuses to hold
 * a remembered category it cannot show.
 */
describe("useQuickAdd — which categories the form offers", () => {
  const dairy = { id: "cat-dairy", name: "Dairy", sort_order: 1 };
  const laptop = {
    ...dairy,
    id: "cat-equipment",
    name: "Laptop",
    context_tag: "equipment",
    sort_order: 2,
  };

  function serveCategories(showModuleData: boolean) {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          settings: showModuleData ? { show_module_data: true } : {},
        }),
      ),
      http.get("*/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        return HttpResponse.json(
          onePage(
            url.searchParams.get("exclude_module_contexts") === "true"
              ? [dairy]
              : [dairy, laptop],
          ),
        );
      }),
    );
  }

  it("leaves module categories out of the picker when the organization keeps them off the general lists", async () => {
    serveCategories(false);

    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.categories).toBeDefined());
    expect(result.current.categories?.map((c) => c.id)).toEqual(["cat-dairy"]);
  });

  it("offers everything once the organization opts in", async () => {
    serveCategories(true);

    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });

    await waitFor(() =>
      expect(result.current.categories?.length).toBeGreaterThan(1),
    );
    expect(result.current.categories?.map((c) => c.id)).toContain(
      "cat-equipment",
    );
  });

  it("keeps the category the record deliberately carries, whatever owns it", async () => {
    serveCategories(false);

    const { result } = renderHook(
      () =>
        useQuickAdd({
          onSuccess: vi.fn(),
          initialData: { category_id: "cat-equipment" },
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(result.current.categories?.map((c) => c.id)).toContain(
        "cat-equipment",
      ),
    );
    expect(result.current.formData.category_id).toBe("cat-equipment");
  });

  it("does not hold a remembered category the picker cannot show", async () => {
    // The scan memory survives a reload and a profile switch, and comes back
    // from localStorage whether or not the category is one this screen may
    // file under. Seeded anyway, the field held an id the reader could not
    // see and the save filed the product as whatever that id named.
    serveCategories(false);
    act(() => {
      useScanStore.setState({ lastCategoryId: "cat-equipment" });
    });

    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.categories).toBeDefined());
    await waitFor(() => expect(result.current.formData.category_id).toBe(""));

    act(() => {
      useScanStore.setState({ lastCategoryId: null });
    });
  });

  describe("what the reader is told about a category that is gone", () => {
    afterEach(() => {
      vi.restoreAllMocks();
      act(() => {
        useScanStore.setState({ lastCategoryId: null });
      });
    });

    it("drops a remembered category without a word", async () => {
      const info = vi.spyOn(toast, "info");
      serveCategories(false);
      act(() => {
        useScanStore.setState({ lastCategoryId: "cat-equipment" });
      });

      const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.categories).toBeDefined());
      await waitFor(() => expect(result.current.formData.category_id).toBe(""));
      expect(info).not.toHaveBeenCalled();
    });

    it("calls a category the reader chose a category, not a place", async () => {
      // One message served both fields, so a reader whose category vanished
      // was told a location had.
      const info = vi.spyOn(toast, "info");
      serveCategories(false);

      const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.categories).toBeDefined());
      act(() => result.current.handleInputChange("category_id", "cat-gone"));

      await waitFor(() =>
        expect(info).toHaveBeenCalledWith(
          "This category is no longer on the list — choose one of the available categories",
        ),
      );
      expect(result.current.formData.category_id).toBe("");
    });
  });
});

describe("useQuickAdd — the fields a category declares", () => {
  // The edit dialog has the matching test ("renders the category's declared
  // fields for the edited record"); this one holds the add side, which
  // passes the category list to the form through its own call.
  it("computes the picked category's declared fields", async () => {
    server.use(
      http.get("*/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              id: "77",
              name: "Laptop",
              code: "LAPTOP",
              sort_order: 1,
              field_definitions: [
                {
                  key: "asset_tag",
                  type: "text",
                  label: "Asset Tag",
                  visible: true,
                  required: false,
                  is_system: true,
                },
                {
                  key: "ram_gb",
                  type: "number",
                  label: "RAM (GB)",
                  visible: true,
                  required: false,
                  is_system: true,
                },
              ],
            },
          ]),
        ),
      ),
    );

    const { result } = renderHook(
      () =>
        useQuickAdd({
          onSuccess: vi.fn(),
          initialData: { category_id: "77" },
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      const keys = result.current.fieldDefinitions.map((f) => f.key);
      expect(keys).toEqual(expect.arrayContaining(["asset_tag", "ram_gb"]));
    });
  });
});

describe("useQuickAdd — what the previous product leaves behind", () => {
  it("carries the shelf and the category, and nothing that described one product", async () => {
    // A tin of peas filed as cold cuts, with the expiry date of the carton
    // before it: the form used to reopen holding the whole of the last
    // product, and the scan that followed only overwrote the fields it knew.
    useFormMemoryStore.getState().setLastItem({
      location_id: "loc-shelf",
      category_id: "cat-1",
      name: "Cold cuts",
      brand: "Brand A",
      expiry_date: "2026-12-01",
    } as never);

    // The form opens before the scan resolves, so the memory is what it is
    // holding when the recognised product arrives — and the merge only
    // overwrites the fields the scan knows about. Whatever it does not know
    // stays: the name is replaced, the expiry date is not.
    const { result, rerender } = renderHook(
      (props: { initialData?: { name: string; barcode: string } }) =>
        useQuickAdd({ onSuccess: vi.fn(), ...props }),
      { wrapper: createWrapper(), initialProps: {} },
    );

    expect(result.current.formData.expiry_date).toBeFalsy();
    expect(result.current.formData.name).toBe("");

    rerender({
      initialData: { name: "Canned peas", barcode: "5906716205928" },
    });

    await waitFor(() =>
      expect(result.current.formData.name).toBe("Canned peas"),
    );
    expect(result.current.formData.expiry_date).toBeFalsy();
    expect(result.current.formData.brand).toBe("");

    act(() => useFormMemoryStore.getState().clear());
  });
});

describe("useQuickAdd — reading a label with the camera", () => {
  const jpeg = () => new File(["x"], "label.jpg", { type: "image/jpeg" });

  const answering = (body: Record<string, unknown>) =>
    vi
      .mocked(visionApi.extract)
      .mockResolvedValue(body as unknown as VisionExtractResult);

  const readLabel = async () => {
    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });
    await act(async () => {
      await result.current.handleVisionAI([jpeg()]);
    });
    return result;
  };

  it("takes the nutrition module's contributed group from `extra`", async () => {
    // These fields used to sit alongside `expiry_date` in one shared type.
    // They arrive namespaced now, and the form has to read them there or a
    // photographed nutrition table quietly stops being recorded.
    answering({
      name: "Mleko",
      expiry_date: "2026-12-31",
      extra: { nutrition: { energy_kcal: 42, proteins: 3.4 } },
    });

    const result = await readLabel();

    await waitFor(() => expect(result.current.formData.name).toBe("Mleko"));
    expect(result.current.formData.expiry_date).toBe("2026-12-31");
    expect(result.current.formData.metadata?.nutrition).toMatchObject({
      energy_kcal: 42,
      proteins: 3.4,
    });
  });

  it("prefers a resolved catalogue entry over the model's reading", async () => {
    // The barcode was legible, so a resolver looked it up. A catalogue name
    // beats a name read off a photograph — but an expiry date does not come
    // from a catalogue, and must survive.
    answering({
      name: "MLEKO 2 PROC",
      brand: null,
      expiry_date: "2026-12-31",
      barcode: "5901234123457",
      resolved: {
        name: "Mleko 2%",
        brand: "Mlekovita",
        metadata: { off_enriched: true },
      },
    });

    const result = await readLabel();

    await waitFor(() => expect(result.current.formData.name).toBe("Mleko 2%"));
    expect(result.current.formData.brand).toBe("Mlekovita");
    expect(result.current.formData.expiry_date).toBe("2026-12-31");
    expect(result.current.formData.metadata?.off_enriched).toBe(true);
  });

  it("calls a reading empty only when no value sits anywhere in it", async () => {
    // The nutrition module's group arrives even from a photo that showed
    // nothing — as a group of nulls — so a reading is judged by its values,
    // not by its keys. One figure in that group is something read.
    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });
    let foundNothing: boolean | undefined;

    answering({
      name: null,
      brand: null,
      extra: { nutrition: { energy_kcal: null, ingredients: null } },
      resolved: null,
    });
    await act(async () => {
      foundNothing = await result.current.handleVisionAI([jpeg()]);
    });
    expect(foundNothing).toBe(true);
    // Nothing read is nothing merged: the form is not marked as photo-filled.
    expect(result.current.formData.metadata?.nutrition_source).toBeUndefined();

    answering({ name: null, extra: { nutrition: { energy_kcal: 42 } } });
    await act(async () => {
      foundNothing = await result.current.handleVisionAI([jpeg()]);
    });
    expect(foundNothing).toBe(false);
    expect(result.current.formData.metadata?.nutrition).toMatchObject({
      energy_kcal: 42,
    });
  });

  it("keeps the reading when nothing resolved the barcode", async () => {
    answering({ name: "Home-made jam", resolved: null });

    const result = await readLabel();

    await waitFor(() =>
      expect(result.current.formData.name).toBe("Home-made jam"),
    );
    expect(result.current.formData.metadata?.off_enriched).toBe(false);
  });
});
