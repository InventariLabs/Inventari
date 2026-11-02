import { act, useState, type ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import DocumentDetailPage from "./DocumentDetailPage";
import * as documentHooks from "@/modules/warehouse/hooks/useDocuments";
import * as documentApprovalHooks from "@/modules/warehouse/hooks/useDocumentApproval";
import * as profileHooks from "@/modules/warehouse/hooks/useDocumentProfile";
import * as scanSessionHooks from "@/modules/warehouse/hooks/useDocumentScanSession";
import * as partnerHooks from "@/modules/partners/hooks/usePartners";
import { serveLocations } from "@/test/serveLocations";
import * as modulesCtx from "@/contexts/ModulesContext";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import type { ApprovalRequest } from "@/modules/approvals/api/approvals";
import { withLanguage } from "@/test/mocks/i18n";
import { documentLine } from "@/test/factories/documents";
import { warehouseDocument } from "@/test/factories/documents";

const workflowMutations = vi.hoisted(() => ({
  confirm: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
  delete: vi.fn(),
  approve: vi.fn(),
  requestApproval: vi.fn(),
  reject: vi.fn(),
}));

const DUPLICATE_MUTATION = {
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
};

const slotSpy = vi.hoisted(() => vi.fn());

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockAuthState = {
  user: { role: "admin", is_superuser: false },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

// Mock the leaf, not the composition: useDocumentCurrency stays real so the
// page is rendered with the resolution chain it actually runs in production.
// Stubbing useDocumentCurrency itself hid the organization fallback and let
// the test claim amounts render unsigned when they never do.
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

vi.mock("@/modules/warehouse/components/DocumentFormModal", () => ({
  default: () => null,
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocument: vi.fn(),
  useDocumentCorrections: vi.fn(() => ({ data: [] })),
  useUpdateDocument: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDocumentWorkflow: vi.fn(() => ({
    confirmDocument: { mutate: workflowMutations.confirm, isPending: false },
    postDocumentNow: { mutate: vi.fn(), isPending: false },
    completeDocument: { mutate: workflowMutations.complete, isPending: false },
    cancelDocument: { mutate: workflowMutations.cancel, isPending: false },
    deleteDocument: { mutate: workflowMutations.delete, isPending: false },
    undoDocument: { mutate: vi.fn(), isPending: false },
    isSavingDraft: false,
    isTransitionPending: false,
  })),
  useDuplicateDocument: () => DUPLICATE_MUTATION,
  useSetLineTarget: () => ({ mutate: vi.fn(), isPending: false }),
  useSetDocumentMetaData: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: vi.fn(() => []),
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartners: vi.fn(),
  usePartner: vi.fn(() => ({ data: undefined, isError: false })),
}));

vi.mock("@/modules/warehouse/hooks/useExtraCosts", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/warehouse/hooks/useExtraCosts")
  >()),
  useExtraCosts: vi.fn(() => ({ data: { editable: false, costs: [] } })),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentApproval", () => ({
  useApproveDocument: vi.fn(() => ({
    mutateAsync: workflowMutations.approve,
    isPending: false,
  })),
  useRequestDocumentApproval: vi.fn(() => ({
    mutateAsync: workflowMutations.requestApproval,
    isPending: false,
  })),
  useRejectDocument: vi.fn(() => ({
    mutateAsync: workflowMutations.reject,
    isPending: false,
  })),
  useDocumentApproval: vi.fn(() => ({ data: null })),
  // The rule itself is the backend's; the page only reads its answer, so the
  // dialog's wording is exercised by handing the page that answer.
  useDocumentApprovalRequirement: vi.fn(() => ({
    data: { approval_required: false, workflow_configured: false },
  })),
}));

// The confirm sentence is threshold-aware, so the page reads the profile.
// Unmocked it would fetch, and the fetch would trip the console gate on
// every test in this file.
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: vi.fn(() => ({ data: undefined })),
}));

// The page reads it through this module: with the hook unmocked the render
// would ask the API two questions no handler in this file answers.
vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: vi.fn(() => ({ data: undefined })),
}));

vi.mock("@/components/Slot", () => ({
  // Named per slot: the page renders more than one now, and a stub that
  // answers to every name made the second one look like a duplicate of the
  // first.
  TypedSlot: (props: unknown) => {
    slotSpy(props);
    const { name } = props as { name: string };
    return <div data-testid={`slot-${name}`} />;
  },
}));

// The page reads useModules to gate the
// approvals data fetch and the approvals slot link.
// Mock it so the page renders without a ModulesProvider — the real hook
// throws "useModules must be used within a ModulesProvider" otherwise.
vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual<typeof modulesCtx>(
    "@/contexts/ModulesContext",
  );
  return {
    ...actual,
    useModules: () => ({
      enabledModules: ["warehouse", "approvals"],
      isModuleEnabled: (name: string) =>
        ["warehouse", "approvals"].includes(name),
      isLoading: false,
      refreshModules: vi.fn(),
    }),
  };
});

function ShellWrapper({ children }: { children: ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});

  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.backTo && <a href={headerData.backTo}>Back</a>}
      {headerData.title && <h1>{headerData.title}</h1>}
      {headerData.statusBadge}
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

async function renderWithRoute() {
  await act(async () => {
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/warehouse/documents/doc-1"]}>
          <Routes>
            <Route
              path="/warehouse/documents/:id"
              element={
                <ShellWrapper>
                  <DocumentDetailPage />
                </ShellWrapper>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
}

function buildDocument(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "INT",
    number: "MM/2026/001",
    status: "DRAFT",
    partner_id: "partner-1",
    source_location_id: "loc-1",
    target_location_id: "loc-2",
    scheduled_date: "2026-04-15",
    notes: "Move stock to staging",
    external_reference: "MOVE-1",
    lines: [
      documentLine({
        id: "line-1",
        document_id: "doc-1",
        item_id: null,
        product_template_id: null,
        name: "Widget",
        brand: null,
        barcode: null,
        quantity: "1",
        batch_number: null,
        expiry_date: null,
        notes: null,
        line_number: 1,
      }),
    ],
    created_by: "user-1",
    confirmed_by: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-04-01T10:00:00Z",
    confirmed_at: null,
    completed_at: null,
    ...overrides,
  });
}

/** The request an approver sent back — the one the card must not restate
 * once the document has moved on from the draft it left behind. */
function rejectedRequest(): ApprovalRequest {
  return {
    id: "req-1",
    organization_id: "org-1",
    workflow_id: "wf-1",
    target_type: "document",
    target_id: "doc-1",
    status: "REJECTED",
    current_stage: 1,
    total_stages: 1,
    created_by: "user-1",
    created_by_name: "Alice",
    meta_data: null,
    workflow_stages: [],
    decisions: [
      {
        id: "d-1",
        stage_order: 1,
        approver_id: "u-2",
        approver_name: "Bob Manager",
        status: "REJECTED",
        notes: "too expensive",
        decided_at: "2026-10-10T09:00:00Z",
        created_at: "2026-10-10T09:00:00Z",
      },
    ],
    created_at: "2026-10-10T08:00:00Z",
  };
}

/** The approvals slot's props, whichever order the page renders slots in. */
function approvalSlotProps() {
  const calls = slotSpy.mock.calls
    .map((call) => call[0] as unknown as { name: string })
    .filter((props) => props.name === "approval_status_badge");
  return calls[calls.length - 1];
}

let locationRequests: URLSearchParams[] = [];

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(documentHooks.useDocumentWorkflow).mockReturnValue({
      confirmDocument: { mutate: workflowMutations.confirm, isPending: false },
      postDocumentNow: { mutate: vi.fn(), isPending: false },
      completeDocument: {
        mutate: workflowMutations.complete,
        isPending: false,
      },
      cancelDocument: { mutate: workflowMutations.cancel, isPending: false },
      deleteDocument: { mutate: workflowMutations.delete, isPending: false },
      undoDocument: { mutate: vi.fn(), isPending: false },
      isSavingDraft: false,
      isTransitionPending: false,
    } as unknown as ReturnType<typeof documentHooks.useDocumentWorkflow>);

    vi.mocked(documentApprovalHooks.useDocumentApproval).mockReturnValue({
      data: null,
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApproval
    >);
    vi.mocked(
      documentApprovalHooks.useDocumentApprovalRequirement,
    ).mockReturnValue({
      data: { approval_required: false, workflow_configured: false },
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApprovalRequirement
    >);
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof scanSessionHooks.useDocumentScanSession>);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument(),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: {
        items: [
          {
            id: "partner-1",
            name: "ACME Supplies",
          },
        ],
        total: 1,
      },
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);
    // The page names the two places the document stands between, by id.
    locationRequests = serveLocations([
      { id: "loc-1", name: "Receiving" },
      { id: "loc-2", name: "Staging Zone" },
      ...Array.from({ length: 300 }, (_, i) => ({
        id: `shelf-${i}`,
        name: `Shelf ${i}`,
      })),
    ]);
  });

  it("shows partner, source, target, and scheduled date metadata", async () => {
    await renderWithRoute();

    expect(screen.getByText("MM/2026/001")).toBeInTheDocument();
    expect(screen.getByText("ACME Supplies")).toBeInTheDocument();
    expect(await screen.findByText("Receiving")).toBeInTheDocument();
    expect(await screen.findByText("Staging Zone")).toBeInTheDocument();
    // The places are named by id: the organization's other shelves are not
    // downloaded to find them.
    const naming = locationRequests.filter((asked) => asked.has("ids"));
    expect(naming.flatMap((asked) => asked.getAll("ids")).sort()).toEqual([
      "loc-1",
      "loc-2",
    ]);
    expect(
      locationRequests.every((asked) => Number(asked.get("limit")) <= 100),
    ).toBe(true);
    // scheduled_date formatted with toLocaleDateString — verify it contains the day
    expect(document.body.textContent).toMatch(
      /Apr.*15|15.*Apr|4.15.2026|15\.4\.2026|15.*kwi|kwi.*15/,
    );
  });

  it("says the partners could not be loaded instead of leaving the picker empty", async () => {
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("boom"),
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);

    await renderWithRoute();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("renders scheduled_date as a day, with no hour attached", async () => {
    // `scheduled_date` is a DATE column — a calendar day, not an instant.
    // Printed through the timestamp formatter it read "Apr 15, 2026, 12:00 AM":
    // midnight, an hour nobody schedules and one that only exists in UTC.
    await renderWithRoute();

    expect(screen.getByText("Apr 15, 2026")).toBeInTheDocument();
  });

  it("renders the approvals slot with the atomic document approve adapter", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.getByTestId("slot-approval_status_badge"),
    ).toBeInTheDocument();
    const props = approvalSlotProps() as unknown as {
      name: string;
      data: {
        targetType: string;
        targetId: string;
        onApprove: (requestId: string) => Promise<void>;
      };
    };
    expect(props.name).toBe("approval_status_badge");
    expect(props.data.targetType).toBe("document");
    expect(props.data.targetId).toBe("doc-1");

    await props.data.onApprove("request-1");
    expect(workflowMutations.approve).toHaveBeenCalledWith({ docId: "doc-1" });
  });

  it("shows no card around an approvals slot that has nothing to say", async () => {
    // A confirmed document with no request: the approvals module renders
    // nothing, and the frame used to stand there empty.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const slot = screen.getByTestId("slot-approval_status_badge");
    expect(slot.closest("[hidden]")).not.toBeNull();
  });

  it("keeps the card while a request waits, for the queue link it carries", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "PENDING_APPROVAL" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const slot = screen.getByTestId("slot-approval_status_badge");
    expect(slot.closest("[hidden]")).toBeNull();
  });

  it("routes request-approval through the document endpoint adapter", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const props = approvalSlotProps() as unknown as {
      data: {
        onRequest: () => Promise<void>;
        onReject: (requestId: string, notes: string) => Promise<void>;
      };
    };

    await props.data.onRequest();
    expect(workflowMutations.requestApproval).toHaveBeenCalledWith({
      docId: "doc-1",
    });

    await props.data.onReject("request-1", "wrong quantities");
    expect(workflowMutations.reject).toHaveBeenCalledWith({
      docId: "doc-1",
      notes: "wrong quantities",
    });
  });

  it("hands the slot the document's own approval request", async () => {
    // The request on the document — the one GET /approvals/documents/{id}/approval
    // answers with even for a viewer the scoped request list blinds. The
    // slot must receive it instead of guessing from that list.
    const documentRequest = {
      id: "req-1",
      organization_id: "org-1",
      workflow_id: "wf-1",
      target_type: "document",
      target_id: "doc-1",
      status: "PENDING",
      current_stage: 1,
      total_stages: 1,
      created_by: "manager-1",
      created_by_name: "Manager",
      meta_data: null,
      workflow_stages: [
        { order: 1, role: "manager", label: "Manager", approver_user_ids: [] },
      ],
      decisions: [],
      created_at: "2026-04-01T10:00:00Z",
      viewer_can_decide: false,
    };
    vi.mocked(documentApprovalHooks.useDocumentApproval).mockReturnValue({
      data: documentRequest,
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApproval
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "PENDING_APPROVAL" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const props = approvalSlotProps() as unknown as {
      data: { approval: unknown };
    };
    expect(props.data.approval).toEqual(documentRequest);
  });

  it("keeps the rejection off a document reworked and confirmed again", async () => {
    // The rejection left a draft; the reader edited it, brought the value
    // under the threshold and confirmed again — no approval was needed, so
    // the header now says CONFIRMED while the only request on the document
    // is still the rejected one. The banner and the panel used to restate
    // it anyway: two statuses at once, and an "edit and re-submit" offered
    // on a document that is already confirmed.
    vi.mocked(documentApprovalHooks.useDocumentApproval).mockReturnValue({
      data: rejectedRequest(),
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApproval
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.queryByTestId("approval-rejected-banner"),
    ).not.toBeInTheDocument();
    const props = approvalSlotProps() as unknown as {
      data: { approval: unknown };
    };
    expect(props.data.approval).toBeNull();
  });

  it("still speaks the rejection on the draft it left behind", async () => {
    // The rejected draft is where the rejection is the present: the banner
    // is the next step there, and nothing may quiet it.
    vi.mocked(documentApprovalHooks.useDocumentApproval).mockReturnValue({
      data: rejectedRequest(),
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApproval
    >);

    await renderWithRoute();

    expect(screen.getByTestId("approval-rejected-banner")).toBeInTheDocument();
  });

  it("names what requesting approval does on a confirmed document", async () => {
    // A confirmed document goes back to the approval queue when its
    // approval is requested — the card must say so before the click.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const props = approvalSlotProps() as unknown as {
      data: { requestConsequence?: string };
    };
    expect(props.data.requestConsequence).toBeTruthy();
  });

  it("names no consequence when the document already awaits approval", async () => {
    // Re-requesting on a parked document changes nothing about the
    // document — its state is the one the request would move it to.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "PENDING_APPROVAL" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const props = approvalSlotProps() as unknown as {
      data: { requestConsequence?: string };
    };
    expect(props.data.requestConsequence).toBeUndefined();
  });
  it.each(["COMPLETED", "CANCELLED"] as const)(
    "does not render the approvals slot for terminal status %s",
    async (status) => {
      vi.mocked(documentHooks.useDocument).mockReturnValue({
        data: buildDocument({ status }),
        isLoading: false,
      } as unknown as ReturnType<typeof documentHooks.useDocument>);

      await renderWithRoute();

      expect(
        screen.queryByTestId("slot-approval_status_badge"),
      ).not.toBeInTheDocument();
    },
  );

  it("offers Undo on a completed receipt and asks before writing the reversal", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ type: "IN", status: "COMPLETED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    await userEvent.click(screen.getByRole("button", { name: "Undo receipt" }));
    expect(screen.getByText("Undo this document?")).toBeInTheDocument();
  });

  it("does not render the approvals slot for a draft", async () => {
    await renderWithRoute();
    expect(
      screen.queryByTestId("slot-approval_status_badge"),
    ).not.toBeInTheDocument();
  });

  it("says on the page how far an open scanning session got, and offers to continue or discard it", async () => {
    // The session a closed sheet left behind used to be named only in the
    // refusal at the last click — by then the reader had already filled in
    // a form over it.
    vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
      data: {
        kind: "receiving",
        id: "session-1",
        status: "active",
        started_at: "2026-10-11T08:00:00Z",
        assigned_to: "user-1",
        doneLines: 1,
        totalLines: 2,
      },
    } as unknown as ReturnType<typeof scanSessionHooks.useDocumentScanSession>);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByTestId("open-scan-session-notice")).toHaveTextContent(
      "lines received: 1/2",
    );
    expect(
      screen.getByRole("button", { name: "Continue (1/2)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Discard scans" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["receiving", "IN"],
    ["picking", "INT"],
  ] as const)(
    "names a finished %s scan that booked nothing, and completes the document in one step",
    async (kind, type) => {
      // Leaving the summary by the back arrow or a closed tab used to leave
      // every line done and nothing booked, with nothing on the page to say
      // so or to finish it from.
      vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
        data: {
          kind,
          id: "session-1",
          status: "finished",
          started_at: "2026-10-11T08:00:00Z",
          assigned_to: "user-1",
        },
      } as unknown as ReturnType<
        typeof scanSessionHooks.useDocumentScanSession
      >);
      vi.mocked(documentHooks.useDocument).mockReturnValue({
        data: buildDocument({
          type,
          status: "CONFIRMED",
          confirmed_at: "2026-04-01T11:00:00Z",
        }),
        isLoading: false,
      } as unknown as ReturnType<typeof documentHooks.useDocument>);

      await renderWithRoute();

      expect(screen.getByText(/no stock is booked yet/)).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Complete and post stock" }),
      );

      expect(workflowMutations.complete).toHaveBeenCalledWith(
        { id: "doc-1", data: undefined },
        expect.anything(),
      );
    },
  );

  it("says nothing about a session the document does not have", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.queryByTestId("open-scan-session-notice"),
    ).not.toBeInTheDocument();
  });

  it("shows an execution section with line status counts", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        lines: [
          documentLine({
            id: "line-1",
            document_id: "doc-1",
            item_id: null,
            product_template_id: null,
            name: "Widget",
            brand: null,
            barcode: null,
            quantity: "5",
            expected_quantity: "5",
            done_quantity: "3",
            discrepancy_code: "SHORTAGE",
            batch_number: null,
            expiry_date: null,
            notes: null,
            line_number: 1,
          }),
          documentLine({
            id: "line-2",
            document_id: "doc-1",
            item_id: null,
            product_template_id: null,
            name: "Cable",
            brand: null,
            barcode: null,
            quantity: "2",
            expected_quantity: "2",
            done_quantity: "2",
            batch_number: null,
            expiry_date: null,
            notes: null,
            line_number: 2,
          }),
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const snapshot = within(
      screen.getByTestId("document-operational-snapshot"),
    );

    expect(screen.getByText("Execution Summary")).toBeInTheDocument();
    expect(snapshot.getByText("Pending")).toBeInTheDocument();
    expect(snapshot.getByText("Partial")).toBeInTheDocument();
    expect(snapshot.getByText("Exception")).toBeInTheDocument();
    expect(snapshot.getByText("Done")).toBeInTheDocument();
    expect(snapshot.getAllByText("1")).toHaveLength(2);
    expect(snapshot.getAllByText("0")).toHaveLength(2);
    // the headline names both counts, because the tiles beside it
    // count lines and the progress counts the summed quantity.
    expect(
      screen.getByText("Lines 1/2 done · Quantity 5/7"),
    ).toBeInTheDocument();
  });

  it("shows line notes in the lines table when present", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        lines: [
          documentLine({
            id: "line-1",
            document_id: "doc-1",
            item_id: null,
            product_template_id: null,
            name: "Widget",
            brand: null,
            barcode: null,
            quantity: "1",
            batch_number: null,
            expiry_date: null,
            notes: "Handle with care",
            line_number: 1,
          }),
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    // The lines render twice — a table from `sm` up, cards below it —
    // so scope the assertion to the table branch.
    const linesTable = screen.getByRole("table");
    expect(
      within(linesTable).getByText("Handle with care"),
    ).toBeInTheDocument();
  });

  it("shows draft actions and hides completion action for draft documents", async () => {
    await renderWithRoute();

    expect(screen.getByRole("button", { name: /Edit/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Move stock/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Delete/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Complete/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Print pick list" }),
    ).not.toBeInTheDocument();
  });

  it("disables execute and picking actions while an approval is pending", async () => {
    vi.mocked(documentApprovalHooks.useDocumentApproval).mockReturnValue({
      data: { id: "req-1", status: "PENDING" },
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApproval
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "CONFIRMED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByRole("button", { name: /Pick items/i })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Scan picking/i }),
    ).toBeDisabled();
  });

  it("shows completion and the way back out for confirmed documents", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.getByRole("button", { name: /Pick items/i }),
    ).toBeInTheDocument();
    // The paper list is offered while the dispatch waits to be picked.
    expect(
      screen.getByRole("button", { name: "Print pick list" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Confirm/i }),
    ).not.toBeInTheDocument();
    // Cancelling is what releases the reservation this document holds, so a
    // manager keeps the way out of a document that will not execute.
    expect(
      screen.getByRole("button", { name: /Cancel document/i }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Delete/i }),
    ).not.toBeInTheDocument();
  });

  it("shows no workflow actions for completed documents", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "COMPLETED",
        confirmed_at: "2026-04-02T09:00:00Z",
        completed_at: "2026-04-03T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.queryByRole("button", { name: /Edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Confirm/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Cancel/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Delete/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Complete/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the shipment a completed dispatch left with", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "OUT",
        status: "COMPLETED",
        confirmed_at: "2026-04-02T09:00:00Z",
        completed_at: "2026-04-03T11:00:00Z",
        shipment: {
          carrier: "DHL",
          tracking_number: "JD0001",
          tracking_url:
            "https://www.dhl.com/global-en/home/tracking.html?tracking-id=JD0001",
          shipped_at: "2026-04-03T11:00:00Z",
          shipped_by_name: "Kamil Wiśniewski",
          package_count: 1,
        },
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.getByRole("heading", { name: "Shipment" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Track parcel JD0001/ }),
    ).toHaveAttribute(
      "href",
      "https://www.dhl.com/global-en/home/tracking.html?tracking-id=JD0001",
    );
  });

  it("shows no shipment card on a document that never shipped", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ status: "COMPLETED" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(
      screen.queryByRole("heading", { name: "Shipment" }),
    ).not.toBeInTheDocument();
  });

  it("names who created the document", async () => {
    // The record carried the creator's name and the header showed only the
    // date; three months later nobody could say whose document it was.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        created_by: "user-7",
        created_by_name: "Kamil Wiśniewski",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Kamil Wiśniewski")).toBeInTheDocument();
    expect(screen.getByText("Created by")).toBeInTheDocument();
  });

  it("names the confirmer and the approver separately", async () => {
    // The approval overwrote the confirmation, so the card named the
    // approver as the one who confirmed the document. Two hands, two names.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T10:00:00Z",
        confirmed_by: "user-kamil",
        confirmed_by_name: "Kamil Wiśniewski",
        approval: {
          request_id: "req-1",
          status: "APPROVED",
          current_stage: 1,
          total_stages: 1,
          created_at: "2026-04-01T10:00:05Z",
          decisions: [
            {
              status: "APPROVED",
              decided_at: "2026-04-01T11:00:00Z",
              decided_by: "user-piotr",
              decided_by_name: "Piotr Nowak",
            },
          ],
        },
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Confirmed by")).toBeInTheDocument();
    expect(screen.getByText("Kamil Wiśniewski")).toBeInTheDocument();
    expect(screen.getByText("Approved by")).toBeInTheDocument();
    expect(screen.getByText("Piotr Nowak")).toBeInTheDocument();
  });

  it("keeps the confirmer, the approver and the canceller apart", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CANCELLED",
        confirmed_at: "2026-04-01T10:00:00Z",
        confirmed_by: "user-kamil",
        confirmed_by_name: "Kamil Wiśniewski",
        cancelled_by: "user-anna",
        cancelled_by_name: "Anna Kowalska",
        cancelled_at: "2026-04-05T14:53:47Z",
        approval: {
          request_id: "req-1",
          status: "APPROVED",
          current_stage: 1,
          total_stages: 1,
          created_at: "2026-04-01T10:00:05Z",
          decisions: [
            {
              status: "APPROVED",
              decided_at: "2026-04-01T11:00:00Z",
              decided_by: "user-piotr",
              decided_by_name: "Piotr Nowak",
            },
          ],
        },
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Kamil Wiśniewski")).toBeInTheDocument();
    expect(screen.getByText("Piotr Nowak")).toBeInTheDocument();
    expect(screen.getByText("Anna Kowalska")).toBeInTheDocument();
    expect(screen.getByText("Approved by")).toBeInTheDocument();
    expect(screen.getByText("Cancelled by")).toBeInTheDocument();
  });

  it("shows a cancelled status progression for cancelled documents", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CANCELLED",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const progressList = screen.getByRole("list", { name: /Status Progress/i });

    expect(within(progressList).getByText("Draft")).toBeInTheDocument();
    expect(within(progressList).getByText("Cancelled")).toBeInTheDocument();
    expect(
      within(progressList).queryByText("Completed"),
    ).not.toBeInTheDocument();
  });

  it("names who cancelled the document and when", async () => {
    // A withdrawal with no author and no time is an unexplained hole in
    // the books: the card has to say who took the document out and when.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CANCELLED",
        cancelled_by: "user-9",
        cancelled_by_name: "Warehouse Manager",
        cancelled_at: "2026-04-05T14:53:47Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Warehouse Manager")).toBeInTheDocument();
    expect(screen.getByText("Cancelled by")).toBeInTheDocument();
  });

  it("tells the reader a cancellation releases stock only when it does", async () => {
    // The reservation sentence was written for issues and shown to every
    // confirmed document — a receipt, which reserves nothing, promised a
    // return to the shelf that never happened.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "IN",
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    await userEvent.click(
      screen.getByRole("button", { name: /Cancel document/i }),
    );
    expect(screen.getByText(/This cannot be undone/i)).toBeInTheDocument();
    expect(screen.queryByText(/stock it reserved/i)).not.toBeInTheDocument();
  });

  it("keeps the reservation sentence for a document that holds one", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "OUT",
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    await userEvent.click(
      screen.getByRole("button", { name: /Cancel document/i }),
    );
    expect(screen.getByText(/stock it reserved/i)).toBeInTheDocument();
  });

  it("dates an approved document's Confirmed rung at the approval, not at the submission the old stamp holds", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        created_at: "2026-04-01T08:00:00Z",
        confirmed_at: "2026-04-01T09:00:00Z",
        confirmed_by: "u-1",
        confirmed_by_name: "Stamp Submitter",
        approval: {
          status: "APPROVED",
          created_at: "2026-04-01T09:00:00Z",
          decisions: [
            { status: "APPROVED", decided_at: "2026-04-01T10:00:00Z" },
          ],
        },
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const progressList = screen.getByRole("list", { name: /Status Progress/i });
    const dated = within(progressList)
      .getAllByRole("listitem")
      .map((li) => li.textContent ?? "")
      .filter((text) => /2026/.test(text));
    const stamps = dated.map((text) => text.replace(/^\D*/, ""));
    // Draft, then the approval and the confirmation it made: the last two
    // read the same moment, and none of them is the 09:00 submission.
    expect(stamps).toHaveLength(3);
    expect(stamps[1]).toBe(stamps[2]);
    expect(stamps[0]).not.toBe(stamps[1]);
    // The rung is dated at the approval, and the confirmation keeps the
    // name of the hand that made it.
    expect(screen.getByText("Stamp Submitter")).toBeInTheDocument();
  });

  it("shows an explicit status progression for confirmed documents", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const progressList = screen.getByRole("list", { name: /Status Progress/i });

    expect(within(progressList).getByText("Draft")).toBeInTheDocument();
    expect(within(progressList).getByText("Confirmed")).toBeInTheDocument();
    expect(within(progressList).getByText("Completed")).toBeInTheDocument();
    expect(within(progressList).getAllByText(/2026/).length).toBeGreaterThan(1);
  });

  it("shows planned and done quantities when execution data is available", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
        lines: [
          documentLine({
            id: "line-1",
            document_id: "doc-1",
            item_id: null,
            product_template_id: null,
            name: "Widget",
            brand: null,
            barcode: null,
            quantity: "8",
            expected_quantity: "8",
            done_quantity: "5",
            discrepancy_code: "SHORTAGE",
            discrepancy_reason: "Supplier short shipped 3 pcs",
            batch_number: null,
            expiry_date: null,
            notes: null,
            line_number: 1,
          }),
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Execution Summary")).toBeInTheDocument();
    expect(
      screen.getByText("1 line still needs attention. Exceptions: 1."),
    ).toBeInTheDocument();
    // summaryExceptions_one, not the base summaryExceptions — with one
    // exception the badge reads "Exception: 1".
    expect(screen.getByText("Exception: 1")).toBeInTheDocument();
    // Summary tile, table row, and the phone card branch.
    expect(screen.getAllByText("Exception")).toHaveLength(3);
    // The summary sentence prints in both variants now — the table row used
    // to carry it as a title only, and a title is gone since then; jsdom
    // renders both variants, so the sentence shows up twice.
    expect(screen.getAllByText("Done 5 / Planned 8")).toHaveLength(2);
    expect(
      screen.getByText("Lines 0/1 done · Quantity 5/8"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Shortage: Supplier short shipped 3 pcs"),
    ).toHaveLength(2);
  });

  it("brings the execution panel into view when the header opens it", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "OUT",
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();
    // The panel mounts below a tall metadata card; on a phone it opens past
    // the fold, so the tap on "Pick items" must carry the reader to it.
    const scrolled = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    scrolled.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Pick items" }));

    expect(scrolled).toHaveBeenCalledOnce();
    // What was scrolled is the panel itself, not some other section of the
    // page that happens to mount at the same time.
    const panel = within(scrolled.mock.instances[0] as HTMLElement);
    expect(panel.getByText("Execute Document")).toBeInTheDocument();
  });

  it("requires a discrepancy code for partial execution and submits it with an optional note", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
        lines: [
          documentLine({
            id: "line-1",
            document_id: "doc-1",
            item_id: "item-1",
            product_template_id: null,
            name: "Widget",
            brand: null,
            barcode: null,
            quantity: "8",
            expected_quantity: "8",
            done_quantity: "0",
            batch_number: null,
            expiry_date: null,
            notes: null,
            line_number: 1,
          }),
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    fireEvent.click(screen.getByRole("button", { name: /Pick items/i }));

    expect(screen.getByText("Execute Document")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Executed Quantity"), {
      target: { value: "3" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /Confirm & Complete/i }),
    );

    // The message appears both globally and next to the field.
    expect(
      screen.getAllByText(
        "Select a discrepancy code when executed quantity is lower than planned.",
      ).length,
    ).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Discrepancy Code"), {
      target: { value: "SHORTAGE" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Note" }));

    fireEvent.change(screen.getByLabelText("Discrepancy Reason"), {
      target: { value: "Supplier short shipped 5 pcs" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Confirm & Complete/i }),
    );

    expect(workflowMutations.complete).toHaveBeenCalledWith(
      {
        id: "doc-1",
        data: {
          lines: [
            {
              line_id: "line-1",
              done_quantity: 3,
              discrepancy_code: "SHORTAGE",
              discrepancy_reason: "Supplier short shipped 5 pcs",
            },
          ],
        },
      },
      expect.any(Object),
    );
  });

  /**
   * Both quantity writers on this page — the execution section's unit counts
   * and the line's own table cell — went through `toLocaleString(undefined)`,
   * which reads the browser's language rather than the interface's.
   */
  it("writes executed quantities with the language's decimal mark", async () => {
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        status: "CONFIRMED",
        confirmed_at: "2026-04-01T11:00:00Z",
        lines: [
          documentLine({
            id: "line-1",
            document_id: "doc-1",
            item_id: null,
            product_template_id: null,
            name: "Widget",
            brand: null,
            barcode: null,
            quantity: "2.5",
            expected_quantity: "2.5",
            done_quantity: "1.5",
            batch_number: null,
            expiry_date: null,
            notes: null,
            line_number: 1,
          }),
        ],
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await withLanguage("pl", async () => {
      await renderWithRoute();

      // The execution section's headline, then the line's own table cell.
      expect(
        screen.getByText("Pozycje 0/1 · Ilość 1,5/2,5"),
      ).toBeInTheDocument();
      // The table row and the phone card both carry the line's quantity —
      // what came in, with the plan in the sentence beside it.
      expect(screen.getAllByText("1,5").length).toBeGreaterThan(0);
      expect(screen.queryByText("1.5")).not.toBeInTheDocument();
      expect(screen.queryByText("2.5")).not.toBeInTheDocument();
    });
  });

  it("signs the totals with the document currency", async () => {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { value_tracking_enabled: true },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "IN",
        number: "IN/2026/001",
        total_net: "100.00",
        total_tax: "23.00",
        total_gross: "123.00",
        currency: "EUR",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("€123.00")).toBeInTheDocument();
  });

  it("signs the totals with the organization currency when the document has none", async () => {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { value_tracking_enabled: true },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "IN",
        number: "IN/2026/001",
        total_net: "100.00",
        total_tax: "23.00",
        total_gross: "123.00",
        currency: null,
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("PLN 123.00")).toBeInTheDocument();
    expect(screen.queryByText("123.00 ?")).not.toBeInTheDocument();
  });

  it("quotes no totals for a transfer, whatever the profile tracks", async () => {
    // The default document here is a move: its totals are stored and
    // registered, and no card on the page quotes them back.
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { value_tracking_enabled: true },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        total_net: "100.00",
        total_tax: "23.00",
        total_gross: "123.00",
        currency: "EUR",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.queryByText(/123\.00/)).not.toBeInTheDocument();
    expect(screen.queryByText("Unit Price")).not.toBeInTheDocument();
  });
  it("offers a way back when the document does not exist", async () => {
    // The not-found state rendered a single sentence: no heading, no link, no
    // way on except the browser's back button.
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: Object.assign(new Error("not found"), {
        isAxiosError: true,
        response: { status: 404 },
        toJSON: () => ({}),
      }),
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    expect(screen.getByText("Document not found")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /back to list/i }),
    ).toBeInTheDocument();
  });

  it("the confirm dialog names the approval queue when the rule asks for one", async () => {
    vi.mocked(
      documentApprovalHooks.useDocumentApprovalRequirement,
    ).mockReturnValue({
      data: { approval_required: true, workflow_configured: true },
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApprovalRequirement
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ type: "IN" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));

    expect(await screen.findByText(/approval queue/)).toBeInTheDocument();
    expect(
      screen.queryByText(/ready for warehouse execution/),
    ).not.toBeInTheDocument();
  });

  it("names the threshold exception when the rule asks for no approval", async () => {
    // Only an organization that has configured a threshold has an
    // exception to name; without one the sentence is a plain confirm.
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { approval_threshold: "100" },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    vi.mocked(
      documentApprovalHooks.useDocumentApprovalRequirement,
    ).mockReturnValue({
      data: { approval_required: false, workflow_configured: false },
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApprovalRequirement
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({ type: "IN" }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();
    fireEvent.click(screen.getByRole("button", { name: "Receive stock" }));

    // The rule says this document is not gated by its type — the profile's
    // value threshold still may send it to the queue server-side, and the
    // sentence names that exception instead of promising an outcome the
    // server may overrule.
    expect(await screen.findByText(/approval threshold/)).toBeInTheDocument();
    expect(
      screen.queryByText(
        /Confirming will send this document to the approval queue/,
      ),
    ).not.toBeInTheDocument();
  });

  it("sends a note the reader emptied as null, not as a key that is missing", async () => {
    const mutate = vi.fn();
    vi.mocked(documentHooks.useUpdateDocument).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useUpdateDocument>);

    vi.mocked(
      documentApprovalHooks.useDocumentApprovalRequirement,
    ).mockReturnValue({
      data: { approval_required: false },
    } as unknown as ReturnType<
      typeof documentApprovalHooks.useDocumentApprovalRequirement
    >);
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: buildDocument({
        type: "CORRECTION",
        notes: "reason for the correction",
      }),
      isLoading: false,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);

    await renderWithRoute();

    const notes = screen.getByRole("textbox", { name: "Notes" });
    await userEvent.clear(notes);
    fireEvent.blur(notes);

    // `undefined` drops the key on the wire and the server reads that as
    // "leave it alone" — the save answered "updated" over an unchanged note
    // (backend AGENTS.md §2b).
    expect(mutate).toHaveBeenCalledWith(
      { id: "doc-1", data: { notes: null } },
      expect.anything(),
    );
  });
});
