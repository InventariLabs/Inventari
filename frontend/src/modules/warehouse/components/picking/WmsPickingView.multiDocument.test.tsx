import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render as rtlRender, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import WmsPickingView from "./WmsPickingView";
import type { WmsPickSession } from "@/modules/warehouse/api/documents";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const START_PATH = "/api/v1/warehouse/picking/start";
const IDS = ["doc-1", "doc-2"];

function line(
  id: string,
  documentId: string,
  documentNumber: string,
  product: string,
  status: "pending" | "picked" | "short" = "pending",
) {
  return {
    id,
    document_line_id: `dl-${id}`,
    document_id: documentId,
    document_number: documentNumber,
    pick_order: 1,
    status,
    picked_quantity: status === "pending" ? 0 : 1,
    bin_location: "A-01",
    product_name: product,
    lot_name: null,
    expected_quantity: 1,
    uom_symbol: "pcs",
  };
}

function buildSession(): WmsPickSession {
  return {
    id: "session-1",
    document_id: "doc-1",
    assigned_to: null,
    status: "active",
    started_at: "2026-04-05T08:00:00Z",
    completed_at: null,
    total_lines: 3,
    picked_lines: 0,
    pending_lines: 3,
    shelf_scan_required: false,
    documents: [doc("doc-1", "WZ/2026/001"), doc("doc-2", "WZ/2026/002")],
    lines: [
      line("l1", "doc-1", "WZ/2026/001", "Widget"),
      line("l2", "doc-2", "WZ/2026/002", "Gadget"),
      line("l3", "doc-2", "WZ/2026/002", "Gizmo"),
    ],
  };
}

function doc(documentId: string, number: string) {
  return {
    document_id: documentId,
    document_number: number,
    document_status: "CONFIRMED",
    status: "picking",
    total_lines: 0,
    picked_lines: 0,
    pending_lines: 0,
  };
}

function render(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

function view() {
  return (
    <WmsPickingView documentId={IDS[0]} documentIds={IDS} onClose={vi.fn()} />
  );
}

describe("WmsPickingView over several dispatches", () => {
  it("starts one session over all the documents, in the order given", async () => {
    let body: unknown = null;
    server.use(
      http.post(START_PATH, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(buildSession());
      }),
    );

    render(view());

    await screen.findByText("Gadget");
    expect(body).toEqual({ document_ids: IDS });
  });

  it("names the document on every line and shows progress per document", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(view());

    await screen.findByText("Gadget");
    const progress = screen.getByRole("list", {
      name: "Documents in this session",
    });
    expect(within(progress).getByText("WZ/2026/001 · 0/1")).toBeInTheDocument();
    expect(within(progress).getByText("WZ/2026/002 · 0/2")).toBeInTheDocument();
    // The row of each line carries its document's number — as text, not in
    // the link colour of the summary's numbers, since nothing here opens.
    const numbers = screen.getAllByText("WZ/2026/002");
    expect(numbers.length).toBeGreaterThanOrEqual(2);
    for (const number of numbers) {
      expect(number.closest("a, button")).toBeNull();
      expect(number.className).not.toMatch(/text-primary/);
    }
  });

  it("summarises each document with a link to it when the session ends", async () => {
    const session = buildSession();
    session.lines = [
      line("l1", "doc-1", "WZ/2026/001", "Widget"),
      line("l2", "doc-2", "WZ/2026/002", "Gadget"),
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/skip",
        () => HttpResponse.json({ status: "skipped", line_id: "l1" }),
      ),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/short-pick",
        () =>
          HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: "l2",
            session_complete: true,
          }),
      ),
    );

    render(view());
    await screen.findByText("Gadget");

    // doc-1's line is skipped, doc-2's comes up short.
    await userEvent.click(screen.getAllByRole("button", { name: "Skip" })[0]);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Skip",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Short pick" }),
    );
    await userEvent.clear(screen.getByLabelText("Final picked quantity"));
    await userEvent.type(screen.getByLabelText("Final picked quantity"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    const second = await screen.findByRole("region", { name: "WZ/2026/002" });
    expect(
      within(second).getByRole("link", { name: "WZ/2026/002" }),
    ).toHaveAttribute("href", "/warehouse/documents/doc-2");
    const first = screen.getByRole("region", { name: "WZ/2026/001" });
    expect(within(first).getByText("1 skipped")).toBeInTheDocument();
  });

  it("refreshes the documents list when the summary is closed", async () => {
    const session = buildSession();
    session.lines = [
      line("l1", "doc-1", "WZ/2026/001", "Widget"),
      line("l2", "doc-2", "WZ/2026/002", "Gadget"),
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/skip",
        () => HttpResponse.json({ status: "skipped", line_id: "l1" }),
      ),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/short-pick",
        () =>
          HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: "l2",
            session_complete: true,
          }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const onClose = vi.fn();

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WmsPickingView
            documentId={IDS[0]}
            documentIds={IDS}
            onClose={onClose}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("Gadget");
    await userEvent.click(screen.getAllByRole("button", { name: "Skip" })[0]);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Skip",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Short pick" }),
    );
    await userEvent.clear(screen.getByLabelText("Final picked quantity"));
    await userEvent.type(screen.getByLabelText("Final picked quantity"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await screen.findByRole("region", { name: "WZ/2026/002" });
    // The summary does not close over a skipped line nobody answered.
    await userEvent.click(screen.getByRole("button", { name: "Not sent" }));
    await screen.findByText(/· Not sent$/);

    invalidate.mockClear();
    await userEvent.click(
      screen.getByRole("button", { name: /complete|done|close/i }),
    );

    expect(onClose).toHaveBeenCalledWith(false, undefined);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["documents"] });
  });

  it("does not ask the document page to complete a document when the session spans several", async () => {
    const session = buildSession();
    session.lines = [
      line("l1", "doc-1", "WZ/2026/001", "Widget"),
      line("l2", "doc-2", "WZ/2026/002", "Gadget"),
    ];
    server.use(
      http.post("/api/v1/warehouse/documents/doc-1/picking/start", () =>
        HttpResponse.json(session),
      ),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/skip",
        () => HttpResponse.json({ status: "skipped", line_id: "l1" }),
      ),
      http.post(
        "/api/v1/warehouse/documents/doc-1/picking/session-1/short-pick",
        () =>
          HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: "l2",
            session_complete: true,
          }),
      ),
    );
    const onClose = vi.fn();

    // Opened from one of the documents, resumed rather than started together.
    render(<WmsPickingView documentId={IDS[0]} onClose={onClose} />);
    await screen.findByText("Gadget");
    await userEvent.click(screen.getAllByRole("button", { name: "Skip" })[0]);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Skip",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Short pick" }),
    );
    await userEvent.clear(screen.getByLabelText("Final picked quantity"));
    await userEvent.type(screen.getByLabelText("Final picked quantity"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await screen.findByRole("region", { name: "WZ/2026/002" });
    await userEvent.click(screen.getByRole("button", { name: "Not sent" }));
    await screen.findByText(/· Not sent$/);
    await userEvent.click(
      screen.getByRole("button", { name: /complete|done|close/i }),
    );

    expect(onClose).toHaveBeenCalledWith(false, undefined);
  });

  describe("a session over one document, however it was opened", () => {
    // A list passes the ids it ticked even when it ticked one, and Resume
    // passes the row's id: the rule is how many documents the session
    // covers, not whether ids were passed.
    function oneDocument() {
      const session = buildSession();
      session.documents = [doc("doc-1", "WZ/2026/001")];
      session.lines = [line("l1", "doc-1", "WZ/2026/001", "Widget")];
      server.use(
        http.post("/api/v1/warehouse/documents/doc-1/picking/start", () =>
          HttpResponse.json(session),
        ),
        http.post(
          "/api/v1/warehouse/documents/doc-1/picking/session-1/short-pick",
          () =>
            HttpResponse.json({
              status: "short_pick_confirmed",
              line_id: "l1",
              product_name: "Widget",
              picked_quantity: 1,
              expected_quantity: 1,
              uom_symbol: "pcs",
              session_complete: true,
              message: "",
            }),
        ),
      );
    }

    async function pickIt() {
      await userEvent.click(
        await screen.findByRole("button", { name: "Pick full amount" }),
      );
      await screen.findByText("Picking complete");
    }

    it("completes the document it was opened from a list over", async () => {
      oneDocument();
      const onClose = vi.fn();
      render(
        <WmsPickingView
          documentId="doc-1"
          documentIds={["doc-1"]}
          onClose={onClose}
          onPack={vi.fn()}
        />,
      );
      await pickIt();

      // The shipping box is on the summary, and closing it completes.
      await userEvent.type(screen.getByLabelText("Carrier"), "DHL");
      await userEvent.click(
        screen.getByRole("button", { name: "Complete and book" }),
      );

      expect(onClose).toHaveBeenCalledWith(true, { carrier: "DHL" }, "doc-1");
    });

    it("offers Pack, which names the document to pack", async () => {
      oneDocument();
      const onPack = vi.fn();
      render(
        <WmsPickingView
          documentId="doc-1"
          documentIds={["doc-1"]}
          onClose={vi.fn()}
          onPack={onPack}
        />,
      );
      await pickIt();

      await userEvent.click(screen.getByRole("button", { name: "Pack" }));

      expect(onPack).toHaveBeenCalledWith(
        expect.objectContaining({ carrier: "" }),
        "doc-1",
      );
    });
  });

  it("shows the backend's sentence when the start is refused, in the reader's language", async () => {
    server.use(
      http.post(START_PATH, () =>
        HttpResponse.json(
          { detail: "Dokument WZ/2026/002 nie jest potwierdzony." },
          { status: 409 },
        ),
      ),
    );

    await withLanguage("pl", async () => {
      render(view());

      expect(
        await screen.findByText("Dokument WZ/2026/002 nie jest potwierdzony."),
      ).toBeInTheDocument();
    });
  });
});
