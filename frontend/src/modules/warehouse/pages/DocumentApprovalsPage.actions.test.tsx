import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { act, screen } from "@testing-library/react";
import { toast } from "sonner";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { documentApprovalApi } from "@/modules/warehouse/api/documents";
import { useAwaitingApprovalDocuments } from "@/modules/warehouse/hooks/useAwaitingApprovalDocuments";
import { warehouseDocument } from "@/test/factories/documents";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import DocumentApprovalsPage from "./DocumentApprovalsPage";

const m = vi.hoisted(() => ({
  navigate: vi.fn(),
  canDecide: true,
  approve: vi.fn(),
  reject: vi.fn(),
  slots: [] as { name: string; data: Record<string, unknown> }[],
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => m.navigate,
}));

vi.mock("@/hooks/useHasPermission", () => ({
  useHasPermission: () => m.canDecide,
}));

vi.mock("@/modules/warehouse/hooks/useAwaitingApprovalDocuments", () => ({
  useAwaitingApprovalDocuments: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentApproval", () => ({
  useDocumentApproval: () => ({
    data: { id: "req-1", target_id: "d1", status: "PENDING" },
  }),
  useApproveDocument: () => ({ mutateAsync: m.approve }),
  useRejectDocument: () => ({ mutateAsync: m.reject }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentLineNames", () => ({
  useDocumentLineNames: (doc: unknown) => doc,
}));
vi.mock("@/modules/warehouse/hooks/useShowDocumentValue", () => ({
  useShowDocumentValue: () => false,
}));
vi.mock("@/hooks/useDocumentCurrency", () => ({
  useDocumentCurrency: () => "PLN",
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useEnabledModulesOptional: () => ["warehouse"],
}));

vi.mock("@/components/Slot", () => ({
  TypedSlot: (props: { name: string; data: Record<string, unknown> }) => {
    m.slots.push(props);
    return null;
  },
}));

function queue(items: WarehouseDocument[], total = items.length) {
  const refetch = vi.fn();
  vi.mocked(useAwaitingApprovalDocuments).mockReturnValue({
    data: { items, total },
    isLoading: false,
    isError: false,
    refetch,
  } as unknown as ReturnType<typeof useAwaitingApprovalDocuments>);
  return refetch;
}

const d1 = warehouseDocument({
  id: "d1",
  number: "INT/1",
  type: "INT",
  status: "PENDING_APPROVAL",
  lines: [],
});
const d2 = warehouseDocument({
  id: "d2",
  number: "INT/2",
  type: "INT",
  status: "PENDING_APPROVAL",
  lines: [],
});

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <DocumentApprovalsPage />
    </PageHeaderContext.Provider>,
  );
}

function lastOffset() {
  const calls = vi.mocked(useAwaitingApprovalDocuments).mock.calls;
  return (calls[calls.length - 1][0] as { offset: number }).offset;
}

/**
 * The queue's own controls: bulk approval behind a confirmation, the pager,
 * the decision slot's adapters and the ways out of an empty queue. These
 * catch a bulk approve that writes before it asks, forgets which documents
 * failed, or approves through the generic endpoint; a pager that does not
 * move; and an empty queue with no way back to the documents.
 */
describe("DocumentApprovalsPage — bulk approval", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.canDecide = true;
    m.slots = [];
  });

  it("approves the ticked documents only after the confirmation", async () => {
    queue([d1, d2]);
    const approve = vi
      .spyOn(documentApprovalApi, "approve")
      .mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("checkbox", { name: "Select INT/1 for bulk action" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Approve 1 document" }),
    );
    expect(approve).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      Array.from(dialog.querySelectorAll("button")).find(
        (b) => b.textContent === "Approve 1 document",
      ) as HTMLElement,
    );
    expect(approve).toHaveBeenCalledWith("d1");
    expect(approve).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("1 document approved");
  });

  it("names the documents that did not go through and keeps them ticked", async () => {
    queue([d1, d2]);
    vi.spyOn(documentApprovalApi, "approve").mockImplementation((id) =>
      id === "d2"
        ? Promise.reject(new Error("no"))
        : Promise.resolve(undefined as never),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("checkbox", { name: /INT\/1/ }));
    await user.click(screen.getByRole("checkbox", { name: /INT\/2/ }));
    await user.click(
      screen.getByRole("button", { name: "Approve 2 documents" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      Array.from(dialog.querySelectorAll("button")).find(
        (b) => b.textContent === "Approve 2 documents",
      ) as HTMLElement,
    );
    expect(toast.error).toHaveBeenCalledWith("Could not approve INT/2");
    expect(screen.getByRole("checkbox", { name: /INT\/2/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /INT\/1/ })).not.toBeChecked();
  });

  it("unticks a document pressed twice", async () => {
    queue([d1]);
    const user = userEvent.setup();
    renderPage();
    const box = screen.getByRole("checkbox", { name: /INT\/1/ });
    await user.click(box);
    await user.click(box);
    expect(box).not.toBeChecked();
    expect(screen.queryByRole("button", { name: /^Approve/ })).toBeNull();
  });

  it("routes the card's decision through the document's own endpoints", async () => {
    queue([d1]);
    renderPage();
    const panel = m.slots
      .filter((s) => s.name === "approval_decision_panel")
      .pop();
    const data = panel?.data as {
      onApprove: (req: { target_id: string }, notes?: string) => Promise<void>;
      onReject: (req: { target_id: string }, notes?: string) => Promise<void>;
    };
    await act(() => data.onApprove({ target_id: "d1" }, "ok"));
    await act(() => data.onReject({ target_id: "d1" }, "no"));
    expect(m.approve).toHaveBeenCalledWith({ docId: "d1", notes: "ok" });
    expect(m.reject).toHaveBeenCalledWith({ docId: "d1", notes: "no" });
  });
});

describe("DocumentApprovalsPage — paging, failure and empty queues", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.canDecide = true;
    m.slots = [];
  });

  it("moves the queue a page on and back", async () => {
    queue([d1], 120);
    const user = userEvent.setup();
    renderPage();
    expect(lastOffset()).toBe(0);
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(lastOffset()).toBe(50);
    await user.click(screen.getByRole("button", { name: "Previous page" }));
    expect(lastOffset()).toBe(0);
  });

  it("asks again from the failure instead of calling the queue empty", async () => {
    const refetch = vi.fn();
    vi.mocked(useAwaitingApprovalDocuments).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as unknown as ReturnType<typeof useAwaitingApprovalDocuments>);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("leads back to the documents from an empty queue", async () => {
    queue([]);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Go to documents" }));
    expect(m.navigate).toHaveBeenCalledWith("/warehouse");
  });

  it("leads back to the documents when the account cannot decide", async () => {
    m.canDecide = false;
    queue([]);
    const user = userEvent.setup();
    renderPage();
    expect(
      screen.getByText("Approving is not something your account can do"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Go to documents" }));
    expect(m.navigate).toHaveBeenCalledWith("/warehouse");
  });
});
