import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  render as rtlRender,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import * as modulesCtx from "@/contexts/ModulesContext";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import WmsPickingView from "./WmsPickingView";
import { DocumentExecutionSection } from "../DocumentExecutionSection";
import { DocumentPackingStep } from "../packing/DocumentPackingStep";
import { WorkItemRow } from "../todo/WorkItemRow";
import { useDocumentsTodo } from "../../hooks/useDocumentsTodo";
import { useDocument } from "../../hooks/useDocuments";
import type { WmsPickSession } from "@/modules/warehouse/api/documents";
import type { WorkItem } from "@/modules/warehouse/types";

/**
 * The screens a session's ending changes, read after the ending without a
 * reload.
 *
 * What the other tests of the endings assert is that the document queries are
 * invalidated. That is a means: the reader looks at the To do row and the
 * document, and these render both from a cache that was filled before the
 * ending and see what they show once it is over.
 */

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: () => ({
    scannerError: null,
    isCameraActive: true,
    isCameraRunning: true,
    setIsCameraActive: vi.fn(),
    restartCamera: vi.fn(),
    startCamera: vi.fn(),
    resumeCamera: vi.fn(),
    pauseCamera: vi.fn(),
    toggleTorch: vi.fn(),
    isTorchOn: false,
  }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

const DOC_A = "doc-a";
const DOC_B = "doc-b";

function session(): WmsPickSession {
  const line = (id: string, documentLineId: string, name: string) => ({
    id,
    document_line_id: documentLineId,
    pick_order: 1,
    status: "pending" as const,
    picked_quantity: 0,
    bin_location: "A-01",
    product_name: name,
    lot_name: null,
    expected_quantity: 2,
    uom_symbol: "pcs",
  });
  return {
    id: "session-1",
    document_id: DOC_A,
    assigned_to: null,
    status: "active",
    started_at: "2026-04-05T08:00:00Z",
    completed_at: null,
    total_lines: 2,
    picked_lines: 0,
    pending_lines: 2,
    shelf_scan_required: false,
    documents: [],
    lines: [line("pick-1", "dl-a", "Widget"), line("pick-2", "dl-b", "Gadget")],
  };
}

function task(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    key: `document:${DOC_A}`,
    kind: "ship",
    state: "todo",
    source_kind: "document",
    source_id: DOC_A,
    overdue: false,
    shelf_scan_required: false,
    next_action: "pick",
    subject: "Bistro Lato",
    number: "WZ/1",
    count: "2",
    document_type: "OUT",
    document_status: "CONFIRMED",
    ...overrides,
  };
}

function TodoRow() {
  const { data } = useDocumentsTodo({ limit: 100, view: "all" });
  return (
    <>
      {data?.work_items.items.map((item) => (
        <WorkItemRow
          key={item.key}
          item={item}
          members={[]}
          canWrite
          canAssign={false}
          onAssign={vi.fn()}
          onToggleDone={vi.fn()}
          onDelete={vi.fn()}
          onStartCount={vi.fn()}
          onPutAway={vi.fn()}
          onReplenish={vi.fn()}
        />
      ))}
    </>
  );
}

function CoveredDocument({ id }: { id: string }) {
  const { data: document } = useDocument(id);
  if (!document) return null;
  return (
    <section aria-label={document.number}>
      <DocumentExecutionSection document={document} isCorrection={false} />
      <DocumentPackingStep
        document={document}
        onComplete={vi.fn()}
        isCompletePending={false}
      />
    </section>
  );
}

function Screens() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(false)}>Leave the sheet</button>
      <TodoRow />
      <CoveredDocument id={DOC_A} />
      <CoveredDocument id={DOC_B} />
      {open && (
        <WmsPickingView
          documentId={DOC_A}
          documentIds={[DOC_A, DOC_B]}
          onClose={vi.fn()}
        />
      )}
    </>
  );
}

function render() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return rtlRender(<Screens />, {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

/** What the server says about the work, changing as the session does. */
function serve() {
  const world = { paused: false, picked: false };
  const dispatch = (id: string, number: string) =>
    warehouseDocument({
      id,
      number,
      type: "OUT",
      status: "CONFIRMED",
      lines: [
        documentLine({
          id: id === DOC_A ? "dl-a" : "dl-b",
          document_id: id,
          quantity: "2",
          expected_quantity: "2",
          done_quantity: (world.picked ? "2" : "0") as never,
          uom: { id: "u", symbol: "pcs", name: "pcs" } as never,
        }),
      ],
    });
  server.use(
    http.post("/api/v1/warehouse/picking/coverage", () =>
      HttpResponse.json({ documents: [] }),
    ),
    http.post("/api/v1/warehouse/picking/start", () =>
      HttpResponse.json(session()),
    ),
    http.post(
      "/api/v1/warehouse/documents/:id/picking/:sessionId/pause",
      () => {
        world.paused = true;
        return HttpResponse.json({});
      },
    ),
    http.get("/api/v1/warehouse/todo", () =>
      HttpResponse.json({
        inbound: { items: [], total: 0 },
        outbound: { items: [], total: 0 },
        decisions: {
          backorders: { items: [], total: 0 },
          approvals: { items: [], total: 0 },
          quarantine: { items: [], total: 0 },
        },
        work_items: {
          items: [
            world.paused
              ? task({ state: "in_progress", next_action: "resume" })
              : task(),
          ],
          total: 1,
        },
      }),
    ),
    http.get("/api/v1/warehouse/documents/:id", ({ params }) =>
      HttpResponse.json(
        dispatch(params.id as string, params.id === DOC_A ? "WZ/1" : "WZ/2"),
      ),
    ),
    // The packing step asks whether a scanning session still holds the
    // document before it offers to pack.
    http.get("/api/v1/warehouse/documents/:id/picking", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/warehouse/documents/:id/receiving", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/warehouse/documents/:id/packages", () =>
      HttpResponse.json({ packages: [], lines: [], editable: true }),
    ),
  );
  return world;
}

describe("the screens a session ending changes", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse"],
      isModuleEnabled: (name: string) => name === "warehouse",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("shows the To do row as In progress with Resume after the sheet is left", async () => {
    serve();
    render();
    const row = await screen.findByRole("button", { name: "Pick" });
    expect(row).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Leave the sheet" }),
    );

    expect(
      await screen.findByRole("button", { name: "Resume" }),
    ).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pick" })).toBeNull();
  });

  it("shows each covered dispatch done, ready to pack and to complete, after a completion", async () => {
    const world = serve();
    server.use(
      http.post(
        "/api/v1/warehouse/documents/:id/picking/:sessionId/short-pick",
        async ({ request }) => {
          const { line_id: lineId } = (await request.json()) as {
            line_id: string;
          };
          // The second answer ends the session, and both dispatches are
          // picked by then.
          const last = lineId === "pick-2";
          world.picked = last || world.picked;
          return HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: lineId,
            product_name: "Widget",
            picked_quantity: 2,
            expected_quantity: 2,
            uom_symbol: "pcs",
            session_complete: last,
            message: "",
          });
        },
      ),
    );
    render();
    for (const number of ["WZ/1", "WZ/2"]) {
      const covered = await screen.findByRole("region", { name: number });
      expect(within(covered).getByText(/Lines 0\/1 done/)).toBeInTheDocument();
    }

    for (const button of await screen.findAllByRole("button", {
      name: "Pick full amount",
    })) {
      await userEvent.click(button);
    }
    expect(await screen.findByText("Picking Complete")).toBeInTheDocument();

    for (const number of ["WZ/1", "WZ/2"]) {
      const covered = screen.getByRole("region", { name: number });
      await waitFor(() =>
        expect(
          within(covered).getByText(/Lines 1\/1 done/),
        ).toBeInTheDocument(),
      );
      expect(within(covered).getByText("Packing")).toBeInTheDocument();
      expect(
        within(covered).getByRole("button", { name: "Complete dispatch" }),
      ).toBeInTheDocument();
    }
  });
});
