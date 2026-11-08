import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LabelPoolPage from "./LabelPoolPage";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockSetHeader = vi.fn();

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe("LabelPoolPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              short_code: "STM-0001",
              label_type: "GENERIC",
              is_assigned: false,
              printed_at: null,
              is_item_deleted: false,
              description: null,
              created_at: new Date().toISOString(),
            },
            {
              id: "2",
              short_code: "STM-0002",
              label_type: "GENERIC",
              is_assigned: false,
              printed_at: null,
              is_item_deleted: false,
              description: null,
              created_at: new Date().toISOString(),
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.post("/api/v1/labels/pool/generate", () =>
        HttpResponse.json({ message: "Success" }, { status: 201 }),
      ),
      http.delete(
        "/api/v1/labels/pool/1",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
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
        // Generating and deleting labels go through the Core labels API,
        // which asks for `items:write`.
        permissions: ["items:read", "items:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("should render label pool with data", async () => {
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText(/STM-0001/i)).toBeInTheDocument();
    expect(screen.getByText(/STM-0002/i)).toBeInTheDocument();
    expect(screen.getByText(/2 labels/i)).toBeInTheDocument();
  });

  it("should register generate button in page header", async () => {
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await screen.findByText(/STM-0001/i);

    expect(mockSetHeader).toHaveBeenCalledWith(
      expect.objectContaining({ actions: expect.anything() }),
    );
  });

  it("should handle download selected labels", async () => {
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    // Select the first label card
    const labelCard = await screen.findByText(/STM-0001/i);
    fireEvent.click(labelCard);

    const downloadBtn = await screen.findByText(/Print Preview/i);
    fireEvent.click(downloadBtn);

    // Should show preview modal - check for multiple instances if needed, or specific role
    const previewTitles = await screen.findAllByText(/Print Preview/i);
    expect(previewTitles.length).toBeGreaterThan(0);
  });

  /**
   * The selection used to own a band of the page: two `flex-1` buttons above
   * the filter row, each half the screen wide on a desktop, present whether or
   * not the selection still mattered.
   */
  it("puts the actions for a selection in a floating toolbar", async () => {
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await screen.findByText(/STM-0001/i);
    expect(screen.queryByRole("toolbar")).toBeNull();

    fireEvent.click(screen.getAllByRole("checkbox")[1]);

    const toolbar = await screen.findByRole("toolbar");
    expect(within(toolbar).getByText("1 selected")).toBeInTheDocument();
    expect(
      within(toolbar).getByRole("button", { name: /Delete Selected/i }),
    ).toBeInTheDocument();
  });

  /**
   * Freshly generated labels carry neither a description nor an item,
   * so the description column was a column of dashes taking width from the
   * columns that had something to say.
   */
  describe("the description column", () => {
    const renderPage = () =>
      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <LabelPoolPage />
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

    it("is dropped when no label on the page fills it", async () => {
      renderPage();

      await screen.findByText(/STM-0001/i);
      expect(screen.queryByText(/Description \(Internal use\)/i)).toBeNull();
    });

    it("is kept as soon as one label fills it", async () => {
      server.use(
        http.get("/api/v1/labels/pool", () =>
          HttpResponse.json({
            items: [
              {
                id: "1",
                short_code: "STM-0001",
                label_type: "GENERIC",
                is_assigned: false,
                printed_at: null,
                is_item_deleted: false,
                description: "Cold storage batch",
                created_at: new Date().toISOString(),
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
            has_more: false,
          }),
        ),
      );

      renderPage();

      await screen.findByText(/STM-0001/i);
      expect(
        screen.getByText(/Description \(Internal use\)/i),
      ).toBeInTheDocument();
      expect(screen.getAllByText("Cold storage batch").length).toBeGreaterThan(
        0,
      );
    });
  });

  /**
   * The preview modal is reachable without checking anything: the row and the
   * card open it for a single label. Its download button read ``selectedIds``,
   * which is empty on that path, and returned before firing a request — no
   * network call, no error, a button that did nothing.
   */
  describe("the download button in the preview", () => {
    const renderPage = () =>
      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <LabelPoolPage />
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

    const captureExport = () => {
      const exported: string[] = [];
      server.use(
        http.get("/api/v1/labels/pool/export/png", ({ request }) => {
          exported.push(
            ...new URL(request.url).searchParams.getAll("label_ids"),
          );
          return new HttpResponse(new Blob(["png"]), {
            headers: { "Content-Type": "image/png" },
          });
        }),
      );
      return exported;
    };

    beforeEach(() => {
      window.URL.createObjectURL = vi.fn(() => "blob:label-batch");
      window.URL.revokeObjectURL = vi.fn();
      // jsdom implements no navigation — the download anchor's click would
      // land on "Not implemented: navigation" after the test ends.
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
        () => {},
      );
    });

    it("exports the label the preview is showing, with nothing checked", async () => {
      const exported = captureExport();

      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        (await screen.findAllByRole("button", { name: /Print Preview/i }))[0],
      );
      // One row, one label in the operation: the action says so, not "batch".
      fireEvent.click(
        await screen.findByRole("button", { name: /Download 1 label/i }),
      );

      await waitFor(() => expect(exported).toEqual(["1"]));
    });

    it("exports every checked label when the preview was opened in bulk", async () => {
      const exported = captureExport();

      renderPage();
      await screen.findByText(/STM-0001/i);

      const checkboxes = screen.getAllByRole("checkbox");
      fireEvent.click(checkboxes[1]);
      fireEvent.click(checkboxes[2]);

      // The selection's actions moved into the floating toolbar, which carries
      // the count itself — so the button no longer repeats it in its label.
      const toolbar = await screen.findByRole("toolbar");
      expect(within(toolbar).getByText("2 selected")).toBeInTheDocument();
      fireEvent.click(
        within(toolbar).getByRole("button", { name: /Print Preview/i }),
      );
      fireEvent.click(
        await screen.findByRole("button", { name: /Download 2 labels/i }),
      );

      await waitFor(() => expect(exported).toEqual(["1", "2"]));
    });

    it("says the operation's size in labels, copies included", async () => {
      // Copies multiply what the file will hold; a name that ignored them
      // would promise one label and deliver three.
      const exported = captureExport();

      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        (await screen.findAllByRole("button", { name: /Print Preview/i }))[0],
      );
      fireEvent.change(await screen.findByLabelText(/copies per label/i), {
        target: { value: "3" },
      });

      const download = await screen.findByRole("button", {
        name: /Download 3 labels/i,
      });
      fireEvent.click(download);

      await waitFor(() => expect(exported).toEqual(["1", "1", "1"]));
    });
  });

  it("should call delete API when trash button clicked", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/labels/pool/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    // By its own test id: the old lookup searched for
    // svg[data-testid="icon-trash2"], which no icon carries, so `if (trashBtn)`
    // meant the test never clicked anything.
    const trashBtn = (await screen.findAllByTestId("label-delete-btn"))[0];
    fireEvent.click(trashBtn);

    // Deletion goes through the in-app ConfirmDialog, not window.confirm —
    // which the old test stubbed, so nothing was ever confirmed.
    const confirmBtn = await screen.findByRole("button", { name: "Delete" });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(deleted).toEqual(["1"]));
  });

  it("gives every icon button a name that says which label it acts on", async () => {
    // Fifty trash icons with no accessible name at all, and a header checkbox
    // that the products list calls "Select all" and this one called nothing.
    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByRole("button", { name: "Delete label STM-0001" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select label STM-0002" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select all" }),
    ).toBeInTheDocument();
  });

  it("does not report an empty pool, or a count of zero, when the request failed", async () => {
    // The invitation this replaces — "no labels yet / generate the first
    // labels" — prints a second set of codes for stickers already on shelves.
    server.use(
      http.get(
        "/api/v1/labels/pool",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(screen.queryByText(/no labels yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 labels/i)).not.toBeInTheDocument();
  });

  it("leaves the primary slot to the header's generate on the empty pool", async () => {
    // The header already carries the view's one filled generate button; the
    // empty pool used to repeat it as a second filled one. The entry
    // stays — demoted, not removed — because the empty pool is where the
    // reader decides to make the first codes.
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <LabelPoolPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const generate = await screen.findByRole("button", {
      name: /generate the first labels/i,
    });
    // EmptyStateAction's filled face is bg-primary-600; the outline carry
    // has neither filled class.
    expect(generate).not.toHaveClass("bg-primary-600");
    expect(generate).not.toHaveClass("bg-primary-700");
  });

  /**
   * The page's own handlers: every one of them is a closure that only a click
   * reaches, and a click that lands nowhere (a stale setter, a wrong id) looks
   * fine until somebody uses the screen.
   */
  describe("what the page's controls do", () => {
    const poolItem = (id: string, code: string) => ({
      id,
      short_code: code,
      label_type: "GENERIC",
      is_assigned: false,
      printed_at: null,
      is_item_deleted: false,
      description: null,
      created_at: new Date().toISOString(),
    });

    const renderPage = () =>
      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <LabelPoolPage />
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

    /** Serves a pool of `total` labels and records every query it is asked. */
    const servePool = (total: number, items = [poolItem("1", "STM-0001")]) => {
      const queries: URLSearchParams[] = [];
      server.use(
        http.get("/api/v1/labels/pool", ({ request }) => {
          queries.push(new URL(request.url).searchParams);
          return HttpResponse.json({
            items,
            total,
            limit: 50,
            offset: 0,
            has_more: false,
          });
        }),
      );
      return queries;
    };

    it("opens the generate form from the header button and closes it again", async () => {
      renderPage();
      await screen.findByText(/STM-0001/i);

      // The page hands its header button to the shell; draw it the way the
      // shell would and press it.
      const header = mockSetHeader.mock.calls.at(-1)?.[0] as {
        actions: React.ReactNode;
      };
      render(<div>{header.actions}</div>);
      fireEvent.click(screen.getByRole("button", { name: "Generate Labels" }));

      expect(
        await screen.findByLabelText("Number of labels (1–500)"),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      await waitFor(() =>
        expect(screen.queryByLabelText("Number of labels (1–500)")).toBeNull(),
      );
    });

    it("sends the next and the previous page as an offset, 50 labels apart", async () => {
      // A button that moved the page number but not the request would leave
      // the first fifty labels on screen under a "51–100" caption.
      const queries = servePool(120);
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      await waitFor(() =>
        expect(queries.map((q) => q.get("offset"))).toContain("50"),
      );

      fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
      await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("0"));
    });

    it("filters by status and returns to the first page when the filter changes", async () => {
      const queries = servePool(120);
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("50"));

      await userEvent.click(screen.getByRole("tab", { name: "Printed" }));

      await waitFor(() => {
        const last = queries.at(-1);
        expect(last?.get("status")).toBe("PRINTED");
        // Staying on offset 50 of a shorter list would show an empty page.
        expect(last?.get("offset")).toBe("0");
      });
    });

    it("offers the whole pool back when a status filter matches nothing", async () => {
      const queries = servePool(0, []);
      renderPage();
      await screen.findByText("No labels yet");

      await userEvent.click(screen.getByRole("tab", { name: "Printed" }));
      fireEvent.click(
        await screen.findByRole("button", { name: "Show all labels" }),
      );

      await waitFor(() => {
        const last = queries.at(-1);
        expect(last?.has("status")).toBe(false);
        expect(last?.get("offset")).toBe("0");
      });
      expect(screen.queryByText("No labels with this status")).toBeNull();
    });

    it("opens the generate form from the empty pool's own entry", async () => {
      servePool(0, []);
      renderPage();

      fireEvent.click(
        await screen.findByRole("button", {
          name: /generate the first labels/i,
        }),
      );

      expect(
        await screen.findByLabelText("Number of labels (1–500)"),
      ).toBeInTheDocument();
    });

    it("selects and clears the whole page from the header checkbox", async () => {
      servePool(2, [poolItem("1", "STM-0001"), poolItem("2", "STM-0002")]);
      renderPage();
      await screen.findByText(/STM-0001/i);

      const all = screen.getByRole("checkbox", { name: "Select all" });
      fireEvent.click(all);
      expect(await screen.findByText("2 selected")).toBeInTheDocument();

      fireEvent.click(all);
      await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
    });

    it("completes a half-made selection instead of clearing it", async () => {
      servePool(2, [poolItem("1", "STM-0001"), poolItem("2", "STM-0002")]);
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        screen.getByRole("checkbox", { name: "Select label STM-0001" }),
      );
      expect(await screen.findByText("1 selected")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
      expect(await screen.findByText("2 selected")).toBeInTheDocument();
    });

    it("drops the selection from the toolbar's clear button", async () => {
      servePool(1);
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getAllByRole("checkbox")[1]);
      await screen.findByRole("toolbar");
      fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));

      await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
    });

    it("deletes every checked label after a confirmation, then clears the selection", async () => {
      servePool(2, [poolItem("1", "STM-0001"), poolItem("2", "STM-0002")]);
      const deleted: string[] = [];
      server.use(
        http.delete("/api/v1/labels/pool/:id", ({ params }) => {
          deleted.push(String(params.id));
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
      const toolbar = await screen.findByRole("toolbar");
      fireEvent.click(
        within(toolbar).getByRole("button", { name: /Delete Selected/i }),
      );
      fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

      await waitFor(() => expect(deleted).toEqual(["1", "2"]));
      await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
      expect(toast.success).toHaveBeenCalledWith("Label deleted");
    });

    it("sends nothing when the bulk delete is not confirmed", async () => {
      servePool(1);
      const deleted: string[] = [];
      server.use(
        http.delete("/api/v1/labels/pool/:id", ({ params }) => {
          deleted.push(String(params.id));
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getAllByRole("checkbox")[1]);
      const toolbar = await screen.findByRole("toolbar");
      fireEvent.click(
        within(toolbar).getByRole("button", { name: /Delete Selected/i }),
      );
      fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull(),
      );
      expect(deleted).toEqual([]);
      expect(screen.getByRole("toolbar")).toBeInTheDocument();
    });

    it("forgets a single label from the selection once it is deleted", async () => {
      // A deleted label that stayed in selectedIds would be sent to the next
      // bulk action and answered with a 404.
      servePool(1);
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(screen.getAllByRole("checkbox")[1]);
      await screen.findByRole("toolbar");

      fireEvent.click(
        screen.getByRole("button", { name: "Delete label STM-0001" }),
      );
      fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

      await waitFor(() => expect(screen.queryByRole("toolbar")).toBeNull());
      expect(toast.success).toHaveBeenCalledWith("Label deleted");
    });

    it("prints the short code when a label has no description to print", async () => {
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        (await screen.findAllByRole("button", { name: /Print Preview/i }))[0],
      );

      // Both pool labels have a null description: the default content must
      // leave something a person can read if the QR will not scan.
      expect(
        await screen.findByRole("radio", {
          name: "Description and short code",
        }),
      ).toHaveAttribute("aria-checked", "true");
    });

    it("closes the print preview from its own close button", async () => {
      server.use(
        http.get(
          "/api/v1/labels/pool/export/png",
          () =>
            new HttpResponse(new Blob(["png"]), {
              headers: { "Content-Type": "image/png" },
            }),
        ),
      );
      window.URL.createObjectURL = vi.fn(() => "blob:preview");
      window.URL.revokeObjectURL = vi.fn();
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        (await screen.findAllByRole("button", { name: /Print Preview/i }))[0],
      );
      // The sheet has a cross in its header and a Close at its foot.
      const close = (
        await screen.findAllByRole("button", { name: "Close" })
      )[1];
      fireEvent.click(close);

      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Close" })).toBeNull(),
      );
    });

    it("tells the reader when the label file could not be produced", async () => {
      server.use(
        http.get(
          "/api/v1/labels/pool/export/png",
          () => new HttpResponse(null, { status: 500 }),
        ),
      );
      renderPage();
      await screen.findByText(/STM-0001/i);

      fireEvent.click(
        (await screen.findAllByRole("button", { name: /Print Preview/i }))[0],
      );
      fireEvent.click(
        await screen.findByRole("button", { name: /Download 1 label/i }),
      );

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
    });

    describe("in the grid", () => {
      const openGrid = async () => {
        renderPage();
        await screen.findByText(/STM-0001/i);
        fireEvent.click(screen.getByRole("button", { name: "Grid view" }));
        return screen.findAllByTestId("label-card");
      };

      it("selects a card by clicking it and opens its preview from the eye", async () => {
        // The preview renders its sheet from the PNG export; answer it and
        // wait for it, or the request outlives the test's own handlers.
        const exported: string[] = [];
        server.use(
          http.get("/api/v1/labels/pool/export/png", ({ request }) => {
            exported.push(
              ...new URL(request.url).searchParams.getAll("label_ids"),
            );
            return new HttpResponse(new Blob(["png"]), {
              headers: { "Content-Type": "image/png" },
            });
          }),
        );
        window.URL.createObjectURL = vi.fn(() => "blob:preview");
        window.URL.revokeObjectURL = vi.fn();
        const cards = await openGrid();

        fireEvent.click(cards[0]);
        expect(await screen.findByText("1 selected")).toBeInTheDocument();

        fireEvent.click(
          within(cards[1]).getByRole("button", { name: "Print Preview" }),
        );
        expect(
          await screen.findByRole("button", { name: /Download 1 label/i }),
        ).toBeInTheDocument();
        await waitFor(() => expect(exported).toEqual(["2"]));
      });

      it("deletes the card's own label after a confirmation", async () => {
        const deleted: string[] = [];
        server.use(
          http.delete("/api/v1/labels/pool/:id", ({ params }) => {
            deleted.push(String(params.id));
            return new HttpResponse(null, { status: 204 });
          }),
        );
        const cards = await openGrid();

        fireEvent.click(within(cards[1]).getByTestId("label-delete-btn"));
        fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

        await waitFor(() => expect(deleted).toEqual(["2"]));
      });
    });
  });

  describe("a label in use", () => {
    it("can be freed from its row, after asking", async () => {
      const freed: string[] = [];
      server.use(
        http.get("/api/v1/labels/pool", () =>
          HttpResponse.json({
            items: [
              {
                id: "9",
                short_code: "OLD-0009",
                label_type: "GENERIC",
                is_assigned: true,
                assigned_item_name: "Router",
                printed_at: null,
                is_item_deleted: false,
                description: null,
                created_at: new Date().toISOString(),
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
            has_more: false,
          }),
        ),
        http.post("/api/v1/labels/pool/:code/unassign", ({ params }) => {
          freed.push(String(params.code));
          return HttpResponse.json({ message: "Label is now free for reuse" });
        }),
      );
      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <LabelPoolPage />
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );
      await screen.findByText("OLD-0009");

      fireEvent.click(
        screen.getByRole("button", { name: "Free label OLD-0009" }),
      );
      expect(freed).toEqual([]);
      fireEvent.click(
        await screen.findByRole("button", { name: "Free label" }),
      );

      await waitFor(() => expect(freed).toEqual(["OLD-0009"]));
    });
  });

  describe("after Generate Labels", () => {
    const poolRow = (id: string, code: string, assigned: boolean) => ({
      id,
      short_code: code,
      label_type: "GENERIC",
      is_assigned: assigned,
      assigned_item_name: assigned ? "Router" : null,
      printed_at: null,
      is_item_deleted: false,
      description: null,
      created_at: new Date().toISOString(),
    });

    it("moves a filter that excludes the new labels to New, where they are listed", async () => {
      let generated = false;
      server.use(
        http.get("/api/v1/labels/pool", ({ request }) => {
          const status = new URL(request.url).searchParams.get("status");
          const items =
            status === "ASSIGNED"
              ? [poolRow("9", "OLD-0009", true)]
              : status === "FREE" && generated
                ? [poolRow("10", "NEW-0010", false)]
                : [];
          return HttpResponse.json({
            items,
            total: items.length,
            limit: 50,
            offset: 0,
            has_more: false,
          });
        }),
        http.post("/api/v1/labels/pool/generate", () => {
          generated = true;
          return HttpResponse.json([{ id: "10" }], { status: 201 });
        }),
      );

      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <LabelPoolPage />
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

      await userEvent.click(await screen.findByRole("tab", { name: "In use" }));
      expect(await screen.findByText("OLD-0009")).toBeInTheDocument();

      // The header's Generate Labels button lives outside the page's tree.
      const { actions } = mockSetHeader.mock.calls.at(-1)![0];
      render(actions);
      fireEvent.click(screen.getByRole("button", { name: /generate labels/i }));
      fireEvent.click(await screen.findByTestId("export-labels-btn"));

      expect(await screen.findByText("NEW-0010")).toBeInTheDocument();
      expect(screen.queryByText("OLD-0009")).toBeNull();
      expect(screen.getByRole("tab", { name: "New" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
  });
});
