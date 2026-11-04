import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import PurchaseOrderFormModal from "./PurchaseOrderFormModal";
import type { PurchaseOrder } from "../types/purchase-orders";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: vi.fn(() => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
    setIsCameraActive: vi.fn(),
  })),
}));

vi.mock("@/hooks/usePartners", () => ({
  usePartners: vi.fn(() => ({
    data: { items: [{ id: "p1", name: "ACME Supplies" }] },
  })),
  usePartner: vi.fn(() => ({ data: null })),
}));

const mutations = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
}));
vi.mock("../hooks/usePurchaseOrders", () => ({
  useCreatePurchaseOrder: () => ({
    mutateAsync: mutations.create,
    isPending: false,
  }),
  useUpdatePurchaseOrder: () => ({
    mutateAsync: mutations.update,
    isPending: false,
  }),
}));

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { lookupByBarcode: vi.fn() },
}));

vi.mock("@/modules/partners/components/PartnerInlineCreate", () => ({
  PartnerInlineCreate: ({ onCancel }: { onCancel: () => void }) => (
    <div data-testid="partner-inline-create">
      <button type="button" onClick={onCancel}>
        Cancel partner
      </button>
    </div>
  ),
}));

vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    createLabel,
    onCreateNew,
  }: {
    createLabel?: string;
    onCreateNew?: (query: string) => void;
  }) =>
    createLabel && onCreateNew ? (
      <button type="button" onClick={() => onCreateNew("Zed")}>
        {createLabel}
      </button>
    ) : null,
}));

const ORDER = {
  id: "po-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "p1",
  scheduled_date: null,
  notes: "keep cold",
  currency: "EUR",
  lines: [
    {
      id: "line-1",
      product_template_id: "pt-1",
      name: "Latte cups",
      quantity_ordered: "3.000",
      unit_price: "2.50",
      tax_rate: "23.00",
      uom_id: null,
    },
  ],
} as unknown as PurchaseOrder;

/**
 * What the order form sends: its lines in the order they stand, an added and
 * then removed line gone, the chosen currency, blank optional values left
 * out; it closes only after the save went through and says why when it did
 * not. A save that kept a removed line, dropped the currency or reported a
 * refusal as success fails here.
 */
describe("PurchaseOrderFormModal — what a save sends", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates the order with its lines and the chosen currency", async () => {
    mutations.create.mockResolvedValue({ id: "po-9" });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={onSuccess} />);

    await user.type(screen.getByPlaceholderText("Product"), "Custom Widget");
    await user.click(screen.getByRole("button", { name: /add line/i }));
    expect(screen.getAllByPlaceholderText("Product")).toHaveLength(2);
    const removes = screen.getAllByRole("button", { name: /remove line/i });
    await user.click(removes[removes.length - 1]);
    expect(screen.getAllByPlaceholderText("Product")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Currency"), {
      target: { value: "EUR" },
    });
    await user.click(screen.getByRole("button", { name: "Create order" }));

    await waitFor(() => expect(mutations.create).toHaveBeenCalledOnce());
    const payload = mutations.create.mock.calls[0][0];
    expect(payload.currency).toBe("EUR");
    expect(payload.notes).toBeNull();
    expect(payload.lines).toHaveLength(1);
    expect(payload.lines[0]).toMatchObject({
      name: "Custom Widget",
      quantity_ordered: 1,
      unit_price: undefined,
      tax_rate: undefined,
    });
    expect(toast.success).toHaveBeenCalledWith("Purchase order created");
    expect(onSuccess).toHaveBeenCalled();
  });

  it("keeps the form open and says why when the save is refused", async () => {
    mutations.create.mockRejectedValue(new Error("boom"));
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={onSuccess} />);
    await user.type(screen.getByPlaceholderText("Product"), "Widget");
    await user.click(screen.getByRole("button", { name: "Create order" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("refuses an order with no lines at all", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    // Each line carries a phone and a desktop remove button.
    await user.click(
      screen.getAllByRole("button", { name: /remove line/i })[0],
    );
    await user.click(screen.getByRole("button", { name: "Create order" }));
    expect(toast.error).toHaveBeenCalled();
    expect(mutations.create).not.toHaveBeenCalled();
  });

  it("updates the order it opened, with its own lines and prices", async () => {
    mutations.update.mockResolvedValue(ORDER);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(
      <PurchaseOrderFormModal
        purchaseOrder={ORDER}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mutations.update).toHaveBeenCalledOnce());
    const { id, data } = mutations.update.mock.calls[0][0];
    expect(id).toBe("po-1");
    expect(data).toMatchObject({
      partner_id: "p1",
      notes: "keep cold",
      currency: "EUR",
    });
    expect(data.lines[0]).toMatchObject({
      product_template_id: "pt-1",
      name: "Latte cups",
      quantity_ordered: 3,
      unit_price: "2.50",
      tax_rate: "23.00",
    });
    expect(mutations.create).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Purchase order updated");
    expect(onSuccess).toHaveBeenCalled();
  });

  it("closes the partner shortcut on its own Cancel, keeping the order form", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    await user.click(
      screen.getByRole("button", { name: "+ Create new partner" }),
    );
    await user.click(screen.getByRole("button", { name: "Cancel partner" }));
    expect(
      screen.queryByTestId("partner-inline-create"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
