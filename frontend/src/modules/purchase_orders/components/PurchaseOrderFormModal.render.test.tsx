import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import PurchaseOrderFormModal from "./PurchaseOrderFormModal";
import { usePartners } from "@/hooks/usePartners";

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: vi.fn(() => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
  })),
}));

vi.mock("@/hooks/usePartners", () => ({
  usePartners: vi.fn(() => ({
    data: { items: [{ id: "p1", name: "ACME Supplies" }] },
  })),
  usePartner: vi.fn(() => ({ data: null })),
}));

vi.mock("../hooks/usePurchaseOrders", () => ({
  useCreatePurchaseOrder: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  useUpdatePurchaseOrder: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
}));

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { lookupByBarcode: vi.fn() },
}));

vi.mock("@/modules/partners/components/PartnerInlineCreate", () => ({
  PartnerInlineCreate: ({
    initialName,
    onCreated,
  }: {
    initialName: string;
    onCreated: (partner: { id: string; type: string }) => void;
    onCancel: () => void;
  }) => (
    <div data-testid="partner-inline-create">
      <span data-testid="partner-inline-name">{initialName}</span>
      <button
        type="button"
        onClick={() => onCreated({ id: "new-partner-1", type: "SUPPLIER" })}
      >
        Confirm partner
      </button>
      <button
        type="button"
        onClick={() => onCreated({ id: "foreign-1", type: "CUSTOMER" })}
      >
        Confirm foreign partner
      </button>
    </div>
  ),
}));

// The PO form partner field is a SearchableCombobox; surface its create-new
// trigger and the selected value so the inline-create test does not depend on
// the popover.
vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    label,
    value,
    createLabel,
    onCreateNew,
  }: {
    label?: string;
    value?: string;
    createLabel?: string;
    onCreateNew?: (query: string) => void;
  }) => (
    <div>
      {label && <span>{label}</span>}
      <span data-testid="partner-value">{value ?? ""}</span>
      {createLabel && onCreateNew && (
        <button type="button" onClick={() => onCreateNew("test-query")}>
          {createLabel}
        </button>
      )}
    </div>
  ),
}));

describe("PurchaseOrderFormModal", () => {
  it("renders create mode header", () => {
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders with an empty line by default", () => {
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("uses the shared wide sheet container", () => {
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByRole("dialog")).toHaveClass("max-w-6xl");
  });

  it("calls onClose when cancel is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not submit when saving with empty lines", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);

    const saveBtn = screen.getByRole("button", { name: "Create Order" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  it("says the suppliers could not be loaded instead of offering none", () => {
    vi.mocked(usePartners).mockReturnValueOnce({
      data: undefined,
      isError: true,
      error: new Error("boom"),
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof usePartners>);
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("renders supplier combobox", () => {
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByText("Supplier")).toBeInTheDocument();
  });

  it("offers a currency selector defaulting to the organization currency", async () => {
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    const currencySelect = screen.getByLabelText("Currency");
    expect(currencySelect.tagName).toBe("SELECT");
    await waitFor(() => expect(currencySelect).toHaveValue("PLN"));
  });

  it("opens inline partner create without closing the order form", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: "+ Create new partner" }),
    );

    expect(screen.getByTestId("partner-inline-create")).toBeInTheDocument();
    expect(screen.getByTestId("partner-inline-name")).toHaveTextContent(
      "test-query",
    );
    // The order form stays mounted, so entered lines survive.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps entered lines and selects the new partner after inline create", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    // Enter a line before opening the partner shortcut.
    await user.type(screen.getByPlaceholderText("Product"), "Custom Widget");

    await user.click(
      screen.getByRole("button", { name: "+ Create new partner" }),
    );
    await user.click(screen.getByRole("button", { name: /confirm partner/i }));

    // The typed line survived the round trip...
    expect(screen.getByDisplayValue("Custom Widget")).toBeInTheDocument();
    // ...and the newly created partner is selected on the supplier field.
    expect(screen.getByTestId("partner-value")).toHaveTextContent(
      "new-partner-1",
    );
  });

  it("refuses a partner the supplier picker does not list and keeps the layer open", async () => {
    const user = userEvent.setup();
    render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: "+ Create new partner" }),
    );
    // A CUSTOMER is a role the order's supplier field never offers; the form
    // must not take it quietly — beneath the placeholder it would look empty
    // while the form read the field as filled. The layer stays open: its type
    // select is the way to a role that fits.
    await user.click(
      screen.getByRole("button", { name: /confirm foreign partner/i }),
    );

    expect(screen.getByTestId("partner-value")).toHaveTextContent("");
    expect(screen.getByTestId("partner-inline-create")).toBeInTheDocument();
  });

  describe("leaving a filled-in sheet", () => {
    async function fillProduct(user: ReturnType<typeof userEvent.setup>) {
      await user.type(screen.getByPlaceholderText("Product"), "Custom Widget");
    }

    async function escapeSheet(user: ReturnType<typeof userEvent.setup>) {
      // The product picker the typing opened owns the first Escape; the
      // sheet gets the next one.
      await user.keyboard("{Escape}");
      await user.keyboard("{Escape}");
    }

    it("closes the product picker on the first Escape and asks only on the next", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);
      expect(await screen.findByText("No products found")).toBeInTheDocument();

      await user.keyboard("{Escape}");

      expect(screen.queryByText("No products found")).not.toBeInTheDocument();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();

      await user.keyboard("{Escape}");

      expect(
        await screen.findByRole("alertdialog", { name: /discard/i }),
      ).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before Escape throws away what was typed", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);

      await escapeSheet(user);

      expect(
        await screen.findByRole("alertdialog", { name: /discard/i }),
      ).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the close button discards it", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);

      await user.click(screen.getByRole("button", { name: "Close" }));

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the cancel button discards it", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);

      await user.click(screen.getByRole("button", { name: /cancel/i }));

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before a click on the backdrop discards it", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);

      const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
      fireEvent.mouseDown(backdrop);
      fireEvent.click(backdrop);

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("keeps the sheet and its lines when the reader chooses to keep editing", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);
      await escapeSheet(user);

      await user.click(
        await screen.findByRole("button", { name: "Keep editing" }),
      );

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByDisplayValue("Custom Widget")).toBeInTheDocument();
    });

    it("closes once the reader confirms the discard", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);
      await fillProduct(user);
      await escapeSheet(user);

      await user.click(await screen.findByRole("button", { name: "Discard" }));

      expect(onClose).toHaveBeenCalledOnce();
    });

    it("closes an untouched sheet without a question", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<PurchaseOrderFormModal onClose={onClose} onSuccess={vi.fn()} />);

      await user.keyboard("{Escape}");

      expect(onClose).toHaveBeenCalledOnce();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });
});
