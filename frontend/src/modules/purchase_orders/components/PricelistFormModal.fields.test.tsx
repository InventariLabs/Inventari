import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";
import {
  PricelistFormModal,
  emptyForm,
  type PricelistFormState,
} from "./PricelistFormModal";

const PRODUCT: CatalogueSearchResult = {
  product_template_id: "tpl-1",
  name: "Latte cups",
  sku: null,
  barcode: null,
  brand: null,
  uom_id: null,
  uom_symbol: null,
  image_url: null,
  is_stub: false,
};

function Harness({
  initial,
  search = vi.fn().mockResolvedValue([PRODUCT]),
  onSave = vi.fn(),
}: {
  initial: PricelistFormState;
  search?: (q: string) => Promise<CatalogueSearchResult[]>;
  onSave?: () => void;
}) {
  const [form, setForm] = useState(initial);
  return (
    <>
      <PricelistFormModal
        open
        form={form}
        onChange={setForm}
        searchProducts={search}
        onProductSelected={(product) => setForm({ ...form, product })}
        onSave={onSave}
        onClose={vi.fn()}
        isSaving={false}
      />
      <output data-testid="state">{JSON.stringify(form)}</output>
    </>
  );
}

const state = (): PricelistFormState =>
  JSON.parse(screen.getByTestId("state").textContent ?? "{}");

/**
 * Each field of the price form writes its own key: a price typed into the
 * minimum quantity, a currency that never reached the form or a validity
 * date that could not be cleared would save a price nobody entered. The
 * validity check refuses an end before the start.
 */
describe("PricelistFormModal — each field writes its own key", () => {
  it("writes price, currency, minimum, notes and dates into the form", async () => {
    const onSave = vi.fn();
    render(
      <Harness
        initial={{
          ...emptyForm,
          product: PRODUCT,
          validFrom: "2026-01-10",
          validTo: "2026-01-20",
        }}
        onSave={onSave}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(
      within(dialog).getByRole("spinbutton", { name: "Price" }),
      {
        target: { value: "7.5" },
      },
    );
    fireEvent.change(within(dialog).getByLabelText("Currency"), {
      target: { value: "EUR" },
    });
    fireEvent.change(
      within(dialog).getByRole("spinbutton", { name: /minimum|min/i }),
      { target: { value: "6" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Notes"), {
      target: { value: "Spring offer" },
    });

    await userEvent.click(
      within(dialog).getByRole("combobox", { name: /valid from/i }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "January 15, 2026" }),
    );
    await userEvent.click(
      within(dialog).getByRole("combobox", { name: /valid to/i }),
    );
    // The product picker has a Clear of its own; the calendar's is the last.
    const clears = await screen.findAllByRole("button", { name: "Clear" });
    await userEvent.click(clears[clears.length - 1]);

    expect(state()).toMatchObject({
      unitPrice: "7.5",
      currency: "EUR",
      minQuantity: "6",
      notes: "Spring offer",
      validFrom: "2026-01-15",
      validTo: "",
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it("refuses an end date before the start date", async () => {
    const onSave = vi.fn();
    render(
      <Harness
        initial={{
          ...emptyForm,
          unitPrice: "3",
          validFrom: "2026-02-10",
          validTo: "2026-02-01",
        }}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("refuses a minimum quantity of zero", async () => {
    const onSave = vi.fn();
    render(
      <Harness
        initial={{ ...emptyForm, unitPrice: "3", minQuantity: "0" }}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("picks a product, clears it, and says when a search finds none", async () => {
    const search = vi
      .fn()
      .mockImplementation(async (q: string) => (q === "lat" ? [PRODUCT] : []));
    render(<Harness initial={emptyForm} search={search} />);
    fireEvent.change(screen.getByLabelText("Product"), {
      target: { value: "lat" },
    });
    fireEvent.click(await screen.findByText("Latte cups"));
    await waitFor(() =>
      expect(state().product?.product_template_id).toBe("tpl-1"),
    );
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(state().product).toBeNull();

    fireEvent.change(screen.getByLabelText("Product"), {
      target: { value: "zzz" },
    });
    expect(await screen.findByText(/zzz/)).toBeInTheDocument();
  });
});
