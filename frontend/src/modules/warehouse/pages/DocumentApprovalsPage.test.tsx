import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { formatDate } from "@/utils/formatters";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import type { TargetApprovalRequest as ApprovalRequest } from "@/lib/moduleRegistry";
import DocumentApprovalsPage from "./DocumentApprovalsPage";

const daysAgo = (days: number) =>
  new Date(Date.now() - days * 24 * 3600 * 1000).toISOString();

// The document and the request it waits on are two records with two authors
// and two moments: a clerk drafts the transfer, somebody else files it for
// approval days later. The card is about the request.
const DOC_CREATED_AT = daysAgo(10);
const FILED_AT = daysAgo(3);

const DOC: WarehouseDocument = {
  id: "d1",
  number: "INT/2026/158",
  type: "INT",
  status: "PENDING_APPROVAL",
  created_at: DOC_CREATED_AT,
  created_by_name: "Administrator",
  partner_snapshot: null,
  source_location_name: "Magazyn Centralny",
  target_location_name: "Sklep Domowy",
  total_gross: "24.50",
  currency: "PLN",
  lines_count: 1,
  lines: [
    {
      id: "l1",
      name: "Mąka żytnia",
      quantity: 2,
      uom_id: "u1",
      uom: { id: "u1", symbol: "kg", name: "kilogram" },
      batch_number: null,
      serial_number: null,
      expiry_date: null,
      notes: null,
      line_number: 1,
    },
  ],
} as unknown as WarehouseDocument;

const APPROVAL: ApprovalRequest = {
  id: "a1",
  organization_id: "org",
  workflow_id: "w1",
  target_type: "document",
  target_id: "d1",
  status: "PENDING",
  current_stage: 1,
  total_stages: 2,
  created_by: "u2",
  created_by_name: "Jan Kowalski",
  meta_data: null,
  workflow_stages: [
    {
      order: 1,
      role: "manager",
      label: "Manager Review",
      approver_user_ids: [],
    },
    {
      order: 2,
      role: "director",
      label: "Director Approval",
      approver_user_ids: [],
    },
  ],
  decisions: [],
  created_at: FILED_AT,
  solvable: true,
  undecidable_reason: null,
} as unknown as ApprovalRequest;

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ api: { get: apiGet } }));

let queueItems: WarehouseDocument[] = [DOC];

vi.mock("@/modules/warehouse/hooks/useAwaitingApprovalDocuments", () => ({
  useAwaitingApprovalDocuments: () => ({
    data: { items: queueItems, total: queueItems.length },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

let approvalData: ApprovalRequest | undefined;

vi.mock("@/modules/warehouse/hooks/useDocumentApproval", () => ({
  useDocumentApproval: () => ({ data: approvalData }),
  useApproveDocument: () => ({ mutateAsync: vi.fn() }),
  useRejectDocument: () => ({ mutateAsync: vi.fn() }),
}));

// The approvals module fills these slots; what it draws in them is its own
// tests' business. Here the slot is a marker that records what the card
// handed it.
const slotSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/Slot", () => ({
  TypedSlot: (props: { name: string; fallback?: ReactNode }) => {
    slotSpy(props);
    return <div data-testid={`slot-${props.name}`}>{props.fallback}</div>;
  },
}));

function slotProps(name: string) {
  return slotSpy.mock.calls
    .map((call) => call[0] as { name: string; data: Record<string, unknown> })
    .filter((props) => props.name === name);
}

vi.mock("@/hooks/useDocumentCurrency", () => ({
  useDocumentCurrency: () => "PLN",
}));

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (amount: string) => `${amount} zł`,
}));

vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual("@/contexts/ModulesContext");
  return {
    ...actual,
    useEnabledModulesOptional: () => ["warehouse", "approvals"],
  };
});

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <DocumentApprovalsPage />
    </PageHeaderContext.Provider>,
  );
}

describe("DocumentApprovalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGet.mockReset();
    approvalData = APPROVAL;
    queueItems = [DOC];
  });

  it("asks the approvals module to name the requests parked beside the queue", () => {
    // A request parked at a stage nobody can decide never reaches this queue,
    // so it used to read as an empty one. The module that owns requests names
    // them; the queue says where a document of its own is shown.
    queueItems = [];
    renderPage();

    expect(screen.getByTestId("slot-approval_parked_requests")).toBeVisible();
    const [call] = slotProps("approval_parked_requests");
    const data = call.data as {
      targetType: string;
      targetHref: (id: string) => string;
    };
    expect(data.targetType).toBe("document");
    expect(data.targetHref("d1")).toBe("/warehouse/documents/d1");
  });

  it("prints line quantities with their unit", () => {
    renderPage();

    // The approver signs off "2 kg", never a bare "2": the unit rides on the
    // document line, and the quantity helper prints the two as one string.
    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    expect(within(card).getByText("× 2 kg")).toBeInTheDocument();
  });

  it("names who filed the request and when — the request's, not the document's", () => {
    renderPage();

    // An approval queue is a queue of things waiting; how long a request has
    // waited is part of the decision. The person and the moment are the
    // request's: the document's author and creation date answer a different
    // question, and printed under "requested this" they answer it wrongly.
    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    const requester = within(card).getByText(/requested this/).parentElement!;
    expect(within(requester).getByText("Jan Kowalski")).toBeInTheDocument();
    expect(
      within(requester).getByText(`· ${formatDate(FILED_AT)}`),
    ).toBeInTheDocument();
    expect(within(card).queryByText("Administrator")).not.toBeInTheDocument();
    expect(
      within(card).queryByText(`· ${formatDate(DOC_CREATED_AT)}`),
    ).not.toBeInTheDocument();
  });

  it("names no requester until the request itself has loaded", () => {
    approvalData = undefined;
    renderPage();

    // The document's author is not a stand-in for the requester, not even
    // for the moment the request is in flight.
    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    expect(within(card).queryByText(/requested this/)).not.toBeInTheDocument();
    expect(within(card).queryByText("Administrator")).not.toBeInTheDocument();
  });

  it("puts the approval progress and the decision in the narrower column", () => {
    renderPage();

    // A full-width card whose interior is one left-aligned stack wastes half
    // the module's width on air (UI_GUIDELINES §3.2b grid scaling): facts
    // live beside the approval progress in a narrower column, which the
    // approvals module fills.
    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    const grid = card.querySelector(".xl\\:grid-cols-12");
    expect(grid).not.toBeNull();
    const decisionColumn = grid!.querySelector(".xl\\:col-span-5");
    expect(decisionColumn).not.toBeNull();
    expect(
      within(decisionColumn as HTMLElement).getByTestId(
        "slot-approval_decision_panel",
      ),
    ).toBeInTheDocument();
  });

  it("hands the decision slot the request and the document's own adapters", () => {
    renderPage();

    const [call] = slotProps("approval_decision_panel");
    expect((call.data as { approval: ApprovalRequest }).approval).toBe(
      APPROVAL,
    );
    expect(typeof call.data.onApprove).toBe("function");
    expect(typeof call.data.onReject).toBe("function");
  });

  it("leaves the decision column out until the request has loaded", () => {
    approvalData = undefined;
    renderPage();

    expect(
      screen.queryByTestId("slot-approval_decision_panel"),
    ).not.toBeInTheDocument();
  });

  it("shows the route a transfer takes", () => {
    renderPage();

    // For an inter-warehouse transfer the direction is the decision: the
    // card carries both ends when the document names them.
    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    expect(within(card).getByText("Magazyn Centralny")).toBeInTheDocument();
    expect(within(card).getByText("Sklep Domowy")).toBeInTheDocument();
  });

  it("names a line the server left unnamed, from the item it points at", async () => {
    // A line written before the write kept a name on it carries only its
    // item: the preview read a bare "× 5 pcs." for a record the reader
    // cannot identify. The name comes from the item, the same read-time
    // fallback the document detail uses.
    apiGet.mockResolvedValue({ data: { name: "Gouda 250 g" } });
    queueItems = [
      {
        ...DOC,
        lines: [{ ...DOC.lines[0], name: null, item_id: "item-1" }],
      },
    ];
    renderPage();

    const card = screen
      .getByText("INT/2026/158")
      .closest<HTMLElement>(".bg-surface-card")!;
    expect(await within(card).findByText("Gouda 250 g")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/items/item-1");
  });
});
