import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import PurchaseOrderDetailPage from "./PurchaseOrderDetailPage";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { downloadBlob } from "@/utils/helpers";
import * as poHooks from "../hooks/usePurchaseOrders";
import type { PurchaseOrder } from "../types/purchase-orders";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/utils/helpers", () => ({ downloadBlob: vi.fn() }));

const enabled = { value: ["purchase_orders"] as string[] };
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: enabled.value,
    isModuleEnabled: (name: string) => enabled.value.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
  useEnabledModulesOptional: () => enabled.value,
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

// The decide right is the `approvals:approve` permission.
vi.mock("@/hooks/useHasPermission", () => ({
  useHasPermission: () => true,
}));

vi.mock("@/hooks/usePartners", () => ({
  usePartner: () => ({
    data: { id: "partner-1", name: "ACME Supplies", email: "acme@test.com" },
  }),
}));

vi.mock("../hooks/usePurchaseOrders", () => ({
  usePurchaseOrder: vi.fn(),
  usePOApprovalRequirement: vi.fn(),
  useLinkedReceipts: vi.fn(),
  useConfirmPurchaseOrder: vi.fn(),
  useCancelPurchaseOrder: vi.fn(),
  useSendPoEmail: vi.fn(),
  useDownloadPoPdf: vi.fn(),
  useApprovePO: vi.fn(),
  useRejectPO: vi.fn(),
  useRequestPOApproval: vi.fn(),
  usePOApprovalRequests: vi.fn(),
  usePOApprovalWorkflowConfigured: () => true,
  usePOSettings: () => ({ data: { approval_required: false } }),
}));

// The card and the edit form are their own components with their own tests;
// here they stand in as buttons that call what the page handed them.
vi.mock("../components/POApprovalStatusCard", () => ({
  POApprovalStatusCard: (props: {
    onApprove: (id: string, notes?: string) => Promise<void>;
    onRequest: () => Promise<void>;
    onReject: (id: string, notes?: string) => Promise<void>;
  }) => (
    <div>
      <button onClick={() => void props.onApprove("req-1", "fine")}>
        card approve
      </button>
      <button onClick={() => void props.onRequest()}>card request</button>
      <button onClick={() => void props.onReject("req-1", "too dear")}>
        card reject
      </button>
    </div>
  ),
}));

vi.mock("../components/PurchaseOrderFormModal", () => ({
  default: (props: { onClose: () => void; onSuccess: () => void }) => (
    <div role="dialog" aria-label="Edit order form">
      <button onClick={props.onClose}>close form</button>
      <button onClick={props.onSuccess}>save form</button>
    </div>
  ),
}));

function po(over: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: "po-1",
    organization_id: "org-1",
    number: "PO/2026/007",
    status: "DRAFT",
    partner_id: "partner-1",
    partner_name: "ACME Supplies",
    scheduled_date: null,
    notes: null,
    currency: "PLN",
    created_by: "user-1",
    confirmed_by: null,
    confirmed_at: null,
    cancelled_by: null,
    cancelled_at: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    lines: [],
    ...over,
  } as PurchaseOrder;
}

type Mutation = { mutateAsync: ReturnType<typeof vi.fn>; isPending: boolean };
const mutation = (): Mutation => ({ mutateAsync: vi.fn(), isPending: false });
let m: Record<
  "confirm" | "cancel" | "send" | "pdf" | "approve" | "reject" | "request",
  Mutation
>;
const refetch = vi.fn();
const refetchReceipts = vi.fn();
const refetchRequests = vi.fn();

function arrange(
  order: PurchaseOrder | undefined,
  extra: Partial<ReturnType<typeof poHooks.usePurchaseOrder>> = {},
) {
  vi.mocked(poHooks.usePurchaseOrder).mockReturnValue({
    data: order,
    isLoading: false,
    isError: false,
    error: null,
    refetch,
    ...extra,
  } as unknown as ReturnType<typeof poHooks.usePurchaseOrder>);
}

function ShellHeader({ children }: { children: React.ReactNode }) {
  const [header, setHeader] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data: header, setHeader }}>
      <header aria-label="Page header">{header.actions}</header>
      <main>{children}</main>
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/purchase-orders/po-1"]}>
        <Routes>
          <Route
            path="/purchase-orders/:id"
            element={
              <ShellHeader>
                <PurchaseOrderDetailPage />
              </ShellHeader>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const header = () => screen.getByRole("banner", { name: "Page header" });

async function confirmIn(dialogTitle: RegExp, button: string) {
  const dialog = await screen.findByRole("alertdialog", { name: dialogTitle });
  await userEvent.click(within(dialog).getByRole("button", { name: button }));
}

/**
 * Each header action opens its dialog and, on confirming, calls the one
 * mutation it names with this order's id — a wired-up-wrong handler (cancel
 * calling confirm, the e-mail losing the reader's language, a failure toasted
 * as success) breaks one of these.
 */
describe("PurchaseOrderDetailPage — header actions reach their mutation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    enabled.value = ["purchase_orders"];
    m = {
      confirm: mutation(),
      cancel: mutation(),
      send: mutation(),
      pdf: mutation(),
      approve: mutation(),
      reject: mutation(),
      request: mutation(),
    };
    vi.mocked(poHooks.useConfirmPurchaseOrder).mockReturnValue(
      m.confirm as unknown as ReturnType<
        typeof poHooks.useConfirmPurchaseOrder
      >,
    );
    vi.mocked(poHooks.useCancelPurchaseOrder).mockReturnValue(
      m.cancel as unknown as ReturnType<typeof poHooks.useCancelPurchaseOrder>,
    );
    vi.mocked(poHooks.useSendPoEmail).mockReturnValue(
      m.send as unknown as ReturnType<typeof poHooks.useSendPoEmail>,
    );
    vi.mocked(poHooks.useDownloadPoPdf).mockReturnValue(
      m.pdf as unknown as ReturnType<typeof poHooks.useDownloadPoPdf>,
    );
    vi.mocked(poHooks.useApprovePO).mockReturnValue(
      m.approve as unknown as ReturnType<typeof poHooks.useApprovePO>,
    );
    vi.mocked(poHooks.useRejectPO).mockReturnValue(
      m.reject as unknown as ReturnType<typeof poHooks.useRejectPO>,
    );
    vi.mocked(poHooks.useRequestPOApproval).mockReturnValue(
      m.request as unknown as ReturnType<typeof poHooks.useRequestPOApproval>,
    );
    vi.mocked(poHooks.useLinkedReceipts).mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: refetchReceipts,
    } as unknown as ReturnType<typeof poHooks.useLinkedReceipts>);
    vi.mocked(poHooks.usePOApprovalRequests).mockReturnValue({
      data: { items: [] },
      isError: false,
      error: null,
      refetch: refetchRequests,
    } as unknown as ReturnType<typeof poHooks.usePOApprovalRequests>);
  });

  it("confirms a draft and says it was confirmed", async () => {
    m.confirm.mutateAsync.mockResolvedValue(po({ status: "CONFIRMED" }));
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Confirm" }),
    );
    await confirmIn(/confirm order PO\/2026\/007/i, "Confirm");
    expect(m.confirm.mutateAsync).toHaveBeenCalledWith("po-1");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order confirmed"),
    );
  });

  it("says a confirmed order went for approval when the server parked it", async () => {
    m.confirm.mutateAsync.mockResolvedValue(po({ status: "PENDING_APPROVAL" }));
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Confirm" }),
    );
    await confirmIn(/confirm order/i, "Confirm");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Purchase order sent for approval",
      ),
    );
  });

  it("toasts the failure, not a success, when confirming is refused", async () => {
    m.confirm.mutateAsync.mockRejectedValue(new Error("nope"));
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Confirm" }),
    );
    await confirmIn(/confirm order/i, "Confirm");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("cancels the order from the overflow menu", async () => {
    m.cancel.mutateAsync.mockResolvedValue(po({ status: "CANCELLED" }));
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "More actions" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel order" }),
    );
    await confirmIn(/cancel order PO\/2026\/007/i, "Cancel order");
    expect(m.cancel.mutateAsync).toHaveBeenCalledWith("po-1");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order cancelled"),
    );
    expect(m.confirm.mutateAsync).not.toHaveBeenCalled();
  });

  it("asks for approval on a draft when a workflow exists", async () => {
    enabled.value = ["purchase_orders", "approvals"];
    m.request.mutateAsync.mockResolvedValue({});
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Request approval" }),
    );
    await confirmIn(/request approval/i, "Request approval");
    expect(m.request.mutateAsync).toHaveBeenCalledWith("po-1");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Approval requested"),
    );
  });

  it("sends the order to the supplier in the reader's language", async () => {
    m.send.mutateAsync.mockResolvedValue({ status: "ok", message: "" });
    arrange(po({ status: "CONFIRMED" }));
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Send to Vendor" }),
    );
    const dialog = await screen.findByRole("alertdialog", {
      name: "Send to Vendor",
    });
    expect(dialog).toHaveTextContent("acme@test.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(m.send.mutateAsync).toHaveBeenCalledWith({
      poId: "po-1",
      lang: "en",
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Email sent to vendor"),
    );
  });

  it("downloads the PDF under a file name without slashes", async () => {
    const blob = new Blob(["%PDF"]);
    m.pdf.mutateAsync.mockResolvedValue(blob);
    arrange(po({ status: "CONFIRMED" }));
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Download PDF" }),
    );
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(blob, "PO_PO-2026-007.pdf"),
    );
    expect(m.pdf.mutateAsync).toHaveBeenCalledWith({
      poId: "po-1",
      lang: "en",
    });
  });

  it("saves no file when the PDF could not be fetched", async () => {
    m.pdf.mutateAsync.mockRejectedValue(new Error("500"));
    arrange(po({ status: "CONFIRMED" }));
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Download PDF" }),
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("approves and rejects a pending request from the header, with the reason", async () => {
    enabled.value = ["purchase_orders"];
    vi.mocked(poHooks.usePOApprovalRequests).mockReturnValue({
      data: {
        items: [
          {
            id: "req-1",
            target_id: "po-1",
            status: "PENDING",
            created_at: "2026-01-02T10:00:00Z",
            viewer_can_decide: true,
            decisions: [],
          },
        ],
      },
      isError: false,
      error: null,
      refetch: refetchRequests,
    } as unknown as ReturnType<typeof poHooks.usePOApprovalRequests>);
    m.approve.mutateAsync.mockResolvedValue({});
    m.reject.mutateAsync.mockResolvedValue({});
    arrange(po({ status: "PENDING_APPROVAL" }));
    renderPage();

    await userEvent.click(
      within(header()).getByRole("button", { name: "Approve" }),
    );
    await confirmIn(/approve order/i, "Approve");
    expect(m.approve.mutateAsync).toHaveBeenCalledWith({ poId: "po-1" });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order approved"),
    );

    await userEvent.click(
      within(header()).getByRole("button", { name: "Reject" }),
    );
    const dialog = await screen.findByRole("alertdialog", {
      name: /reject order/i,
    });
    await userEvent.type(
      within(dialog).getByLabelText("Reason for rejection"),
      "  over budget  ",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Reject" }),
    );
    expect(m.reject.mutateAsync).toHaveBeenCalledWith({
      poId: "po-1",
      notes: "over budget",
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Purchase order rejected"),
    );
  });

  it("hands the approval card mutations bound to this order", async () => {
    enabled.value = ["purchase_orders", "approvals"];
    arrange(po({ status: "PENDING_APPROVAL" }));
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "card approve" }));
    await userEvent.click(screen.getByRole("button", { name: "card request" }));
    await userEvent.click(screen.getByRole("button", { name: "card reject" }));
    expect(m.approve.mutateAsync).toHaveBeenCalledWith({
      poId: "po-1",
      notes: "fine",
    });
    expect(m.request.mutateAsync).toHaveBeenCalledWith("po-1");
    expect(m.reject.mutateAsync).toHaveBeenCalledWith({
      poId: "po-1",
      notes: "too dear",
    });
  });

  it("opens the edit form and closes it on cancel and on save", async () => {
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Edit" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "close form" }));
    expect(
      screen.queryByRole("dialog", { name: "Edit order form" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Edit" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "save form" }));
    expect(
      screen.queryByRole("dialog", { name: "Edit order form" }),
    ).not.toBeInTheDocument();
  });

  it("closes a dialog on cancel without calling anything", async () => {
    arrange(po());
    renderPage();
    await userEvent.click(
      within(header()).getByRole("button", { name: "Confirm" }),
    );
    const dialog = await screen.findByRole("alertdialog", {
      name: /confirm order/i,
    });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(m.confirm.mutateAsync).not.toHaveBeenCalled();
  });

  it("retries the order, its receipts and the approval requests separately", async () => {
    enabled.value = ["purchase_orders", "approvals"];
    vi.mocked(poHooks.usePOApprovalRequests).mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("boom"),
      refetch: refetchRequests,
    } as unknown as ReturnType<typeof poHooks.usePOApprovalRequests>);
    vi.mocked(poHooks.useLinkedReceipts).mockReturnValue({
      data: [],
      isLoading: false,
      isError: true,
      refetch: refetchReceipts,
    } as unknown as ReturnType<typeof poHooks.useLinkedReceipts>);
    arrange(po());
    renderPage();
    const retries = screen.getAllByRole("button", { name: /try again|retry/i });
    for (const r of retries) await userEvent.click(r);
    expect(refetchRequests).toHaveBeenCalled();
    expect(refetchReceipts).toHaveBeenCalled();
  });

  it("offers a retry for an order that failed to load, not a not-found page", async () => {
    arrange(undefined, { isError: true, error: new Error("500") });
    renderPage();
    await userEvent.click(
      screen.getByRole("button", { name: /try again|retry/i }),
    );
    expect(refetch).toHaveBeenCalled();
  });
});
