import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render as rtlRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import WmsPickingView from "./WmsPickingView";
import type { WmsPickSession } from "@/modules/warehouse/api/documents";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const COVERAGE_PATH = "/api/v1/warehouse/picking/coverage";
const START_MANY = "/api/v1/warehouse/picking/start";
const START_ONE = "/api/v1/warehouse/documents/doc-1/picking/start";
const IDS = ["doc-1", "doc-2"];

function session(documentIds: string[]): WmsPickSession {
  return {
    id: "session-1",
    document_id: documentIds[0],
    assigned_to: null,
    status: "active",
    started_at: "2026-04-05T08:00:00Z",
    completed_at: null,
    total_lines: documentIds.length,
    picked_lines: 0,
    pending_lines: documentIds.length,
    shelf_scan_required: false,
    documents: documentIds.map((id) => ({
      document_id: id,
      document_number: `WZ/${id}`,
      document_status: "CONFIRMED",
      status: "picking",
      total_lines: 1,
      picked_lines: 0,
      pending_lines: 1,
    })),
    lines: documentIds.map((id, index) => ({
      id: `l${index}`,
      document_line_id: `dl-${index}`,
      document_id: id,
      document_number: `WZ/${id}`,
      pick_order: index,
      status: "pending",
      picked_quantity: 0,
      bin_location: "A-01",
      product_name: `Product ${id}`,
      lot_name: null,
      expected_quantity: 1,
      uom_symbol: "pcs",
    })),
  };
}

const SHORT_DOC_2 = {
  documents: [
    {
      document_id: "doc-2",
      document_number: "WZ/doc-2",
      lines: [
        { product_name: "Gadget", uom_symbol: "pcs", ordered: 3, available: 1 },
      ],
    },
  ],
};

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

describe("WmsPickingView names what stock cannot cover before the walk", () => {
  it("lists the short lines and starts nothing until the person chooses", async () => {
    const started = vi.fn();
    server.use(
      http.post(COVERAGE_PATH, () => HttpResponse.json(SHORT_DOC_2)),
      http.post(START_MANY, () => {
        started();
        return HttpResponse.json(session(IDS));
      }),
    );

    render(view());

    expect(await screen.findByText("WZ/doc-2")).toBeInTheDocument();
    expect(screen.getByText(/Gadget/)).toHaveTextContent(/3/);
    expect(screen.getByText(/Gadget/)).toHaveTextContent(/1/);
    expect(started).not.toHaveBeenCalled();
  });

  it("starts without the short documents when asked to", async () => {
    let called = "";
    server.use(
      http.post(COVERAGE_PATH, () => HttpResponse.json(SHORT_DOC_2)),
      http.post(START_ONE, () => {
        called = "one";
        return HttpResponse.json(session(["doc-1"]));
      }),
      http.post(START_MANY, () => {
        called = "many";
        return HttpResponse.json(session(IDS));
      }),
    );

    render(view());
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Start without these documents",
      }),
    );

    await screen.findByText("Product doc-1");
    expect(called).toBe("one");
    expect(screen.queryByText("Product doc-2")).not.toBeInTheDocument();
  });

  it("starts over every document when asked to start anyway", async () => {
    let body: unknown = null;
    server.use(
      http.post(COVERAGE_PATH, () => HttpResponse.json(SHORT_DOC_2)),
      http.post(START_MANY, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(session(IDS));
      }),
    );

    render(view());
    await userEvent.click(
      await screen.findByRole("button", { name: "Start anyway" }),
    );

    await waitFor(() => expect(body).toEqual({ document_ids: IDS }));
  });

  it("offers only to start anyway when every document is short", async () => {
    server.use(
      http.post(COVERAGE_PATH, () =>
        HttpResponse.json({
          documents: [
            { ...SHORT_DOC_2.documents[0], document_id: "doc-1" },
            SHORT_DOC_2.documents[0],
          ],
        }),
      ),
    );

    render(view());

    await screen.findByRole("button", { name: "Start anyway" });
    expect(
      screen.queryByRole("button", { name: "Start without these documents" }),
    ).not.toBeInTheDocument();
  });
});
