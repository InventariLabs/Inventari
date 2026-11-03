import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { POLinesSection, type POLineInput } from "./POLinesSection";

vi.mock("@/modules/warehouse/moduleApi", () => ({
  useProductSearch: () => ({
    results: [
      {
        product_template_id: "tpl-1",
        name: "Ground coffee",
        purchase_price: "45.00",
      },
      { product_template_id: "tpl-2", name: "Ground cocoa" },
    ],
    isLoading: false,
    search: vi.fn(),
    clearSearch: vi.fn(),
  }),
}));

const emptyLine: POLineInput = {
  id: "line-1",
  product_template_id: null,
  name: "",
  sku: null,
  barcode: null,
  brand: null,
  image_url: null,
  quantity_ordered: 1,
  unit_price: "",
  tax_rate: "",
  uom_id: null,
};

function renderSection(line: POLineInput, onUpdateData = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <POLinesSection
          lines={[line]}
          scanOpen={false}
          scanLoading={false}
          isCameraActive={false}
          scannerError={null}
          isTorchOn={false}
          onToggleScan={vi.fn()}
          onAddLine={vi.fn()}
          onToggleTorch={vi.fn()}
          onManualCode={vi.fn()}
          onUpdateData={onUpdateData}
          onRemove={vi.fn()}
          t={(key) => key}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onUpdateData;
}

async function pick(name: RegExp) {
  await userEvent.type(screen.getAllByRole("combobox")[0], "Gr");
  await userEvent.click(await screen.findByText(name));
}

describe("POLinesSection product pick", () => {
  it("starts the line's price from what the product last cost", async () => {
    const onUpdateData = renderSection(emptyLine);

    await pick(/ground coffee/i);

    expect(onUpdateData).toHaveBeenCalledWith(
      "line-1",
      expect.objectContaining({
        product_template_id: "tpl-1",
        unit_price: "45.00",
      }),
    );
  });

  it("leaves the price alone for a product that has none", async () => {
    const onUpdateData = renderSection(emptyLine);

    await pick(/ground cocoa/i);

    const [, update] = onUpdateData.mock.calls[0];
    expect(update).not.toHaveProperty("unit_price");
  });

  it("keeps a price already typed on the line", async () => {
    const onUpdateData = renderSection({ ...emptyLine, unit_price: "40" });

    await pick(/ground coffee/i);

    const [, update] = onUpdateData.mock.calls[0];
    expect(update).not.toHaveProperty("unit_price");
  });
});
