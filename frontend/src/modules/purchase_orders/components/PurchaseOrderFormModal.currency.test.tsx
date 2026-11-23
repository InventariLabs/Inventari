import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import PurchaseOrderFormModal from "./PurchaseOrderFormModal";

/**
 * A price a product pick proposes is what the product last cost, in the
 * organization's currency. When the order's currency changes after the pick,
 * that figure would read as a price in the new currency, so it is cleared; a
 * price the reader typed is theirs and stays.
 */

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

vi.mock("@/modules/warehouse/moduleApi", () => ({
  useProductSearch: () => ({
    results: [
      {
        product_template_id: "tpl-1",
        name: "Ground coffee",
        purchase_price: "45.00",
      },
    ],
    isLoading: false,
    search: vi.fn(),
    clearSearch: vi.fn(),
  }),
}));

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
  usePartners: vi.fn(() => ({ data: { items: [] } })),
  usePartner: vi.fn(() => ({ data: null })),
}));

vi.mock("../hooks/usePurchaseOrders", () => ({
  useCreatePurchaseOrder: vi.fn(() => ({ mutateAsync: vi.fn() })),
  useUpdatePurchaseOrder: vi.fn(() => ({ mutateAsync: vi.fn() })),
}));

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { lookupByBarcode: vi.fn() },
}));

// The supplier field is a search too; standing in for it keeps the line's
// product search the only one on the form.
vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: () => null,
}));

async function pickCoffee() {
  const user = userEvent.setup();
  render(<PurchaseOrderFormModal onClose={vi.fn()} onSuccess={vi.fn()} />);
  // The currency select is a combobox as well; the product search is the
  // first one typed into.
  const [search] = screen
    .getAllByRole("combobox")
    .filter((field) => field.tagName === "INPUT");
  await user.type(search, "Gr");
  await user.click(await screen.findByText(/ground coffee/i));
  await waitFor(() =>
    expect(screen.getAllByDisplayValue("45.00").length).toBeGreaterThan(0),
  );
  return user;
}

describe("PurchaseOrderFormModal currency change", () => {
  it("clears a price the product pick proposed", async () => {
    const user = await pickCoffee();

    await user.selectOptions(screen.getByLabelText("Currency"), "EUR");

    await waitFor(() =>
      expect(screen.queryAllByDisplayValue("45.00")).toHaveLength(0),
    );
  });

  it("keeps a price the reader typed", async () => {
    const user = await pickCoffee();
    const [price] = screen.getAllByDisplayValue("45.00");
    await user.clear(price);
    await user.type(price, "40");

    await user.selectOptions(screen.getByLabelText("Currency"), "EUR");

    expect(screen.getAllByDisplayValue("40").length).toBeGreaterThan(0);
  });
});
