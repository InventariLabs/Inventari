import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, it, expect, vi } from "vitest";
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

const organization = vi.hoisted(() => ({
  currency: undefined as string | undefined,
}));
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => organization.currency,
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

function renderSection(
  line: POLineInput,
  onUpdateData = vi.fn(),
  currency?: string,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <POLinesSection
          lines={[line]}
          currency={currency}
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

/** What the pick itself wrote: the calls before it are the typed search. */
function pickUpdate(onUpdateData: ReturnType<typeof vi.fn>) {
  const call = onUpdateData.mock.calls.find(
    ([, data]) => data.product_template_id,
  );
  return call?.[1];
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

    const update = pickUpdate(onUpdateData);
    expect(update).toMatchObject({ product_template_id: "tpl-2" });
    expect(update).not.toHaveProperty("unit_price");
  });

  it("keeps a price already typed on the line", async () => {
    const onUpdateData = renderSection({ ...emptyLine, unit_price: "40" });

    await pick(/ground coffee/i);

    const update = pickUpdate(onUpdateData);
    expect(update).toMatchObject({ product_template_id: "tpl-1" });
    expect(update).not.toHaveProperty("unit_price");
  });

  describe("on an order with a stated currency", () => {
    afterEach(() => {
      organization.currency = undefined;
    });

    it("proposes the price when the order is in the organization's currency", async () => {
      organization.currency = "PLN";
      const onUpdateData = renderSection(emptyLine, vi.fn(), "PLN");

      await pick(/ground coffee/i);

      expect(pickUpdate(onUpdateData)).toMatchObject({ unit_price: "45.00" });
    });

    it("proposes nothing on an order in another currency", async () => {
      organization.currency = "PLN";
      const onUpdateData = renderSection(emptyLine, vi.fn(), "EUR");

      await pick(/ground coffee/i);

      const update = pickUpdate(onUpdateData);
      expect(update).toMatchObject({ product_template_id: "tpl-1" });
      expect(update).not.toHaveProperty("unit_price");
    });
  });

  describe("with the line kept in state", () => {
    function Harness() {
      const [line, setLine] = useState<POLineInput>(emptyLine);
      return (
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
          onUpdateData={(_id, data) =>
            setLine((prev) => ({ ...prev, ...data }))
          }
          onRemove={vi.fn()}
          t={(key) => (key === "common:actions.clear" ? "Clear product" : key)}
        />
      );
    }

    function renderHarness() {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <Harness />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    }

    async function clearProduct() {
      await userEvent.click(
        screen.getAllByRole("button", { name: "Clear product" })[0],
      );
    }

    it("drops the price proposed for a product when another one without a price is picked", async () => {
      renderHarness();
      await pick(/ground coffee/i);
      expect(screen.getAllByDisplayValue("45.00").length).toBeGreaterThan(0);

      await clearProduct();
      await pick(/ground cocoa/i);

      // Both the desktop and the mobile layout render a price input, and the
      // state may still be settling right after the pick.
      await waitFor(() =>
        expect(screen.queryAllByDisplayValue("45.00")).toHaveLength(0),
      );
    });

    it("keeps a price typed over the proposed one when another product is picked", async () => {
      renderHarness();
      await pick(/ground coffee/i);
      const [price] = screen.getAllByDisplayValue("45.00");
      await userEvent.clear(price);
      await userEvent.type(price, "40");

      await clearProduct();
      await pick(/ground cocoa/i);

      expect(screen.getAllByDisplayValue("40").length).toBeGreaterThan(0);
    });
  });
});
