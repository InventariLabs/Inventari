import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { serveLocations } from "@/test/serveLocations";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";
import {
  ReorderRuleFormModal,
  emptyForm,
  type RuleFormState,
} from "./ReorderRuleFormModal";

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

/** Holds the form the way the page does, and shows what it holds. */
function Harness({
  initial,
  onSave = vi.fn(),
  onClose = vi.fn(),
  onPartnerSearch = vi.fn(),
}: {
  initial: RuleFormState;
  onSave?: () => void;
  onClose?: () => void;
  onPartnerSearch?: (q: string) => void;
}) {
  const [form, setForm] = useState(initial);
  return (
    <>
      <ReorderRuleFormModal
        open
        form={form}
        onChange={setForm}
        searchProducts={vi.fn().mockResolvedValue([PRODUCT])}
        onProductSelected={(product) => setForm({ ...form, product })}
        partnerOptions={[{ id: "p-1", name: "ACME" }]}
        onPartnerSearch={onPartnerSearch}
        partnersLoading={false}
        onSave={onSave}
        onClose={onClose}
        isSaving={false}
      />
      <output data-testid="state">{JSON.stringify(form)}</output>
    </>
  );
}

const state = (): RuleFormState =>
  JSON.parse(screen.getByTestId("state").textContent ?? "{}");

/**
 * Every field of the rule form writes its own key of the form and no other:
 * a handler that wrote the max into the min, dropped the notes, or left the
 * cleared product in place would save a rule nobody typed.
 */
describe("ReorderRuleFormModal — each field writes its own key", () => {
  it("writes thresholds, supplier, notes and location into the form", async () => {
    serveLocations([{ id: "loc-1", name: "Cold Storage" }]);
    const onSave = vi.fn();
    render(
      <Harness initial={{ ...emptyForm, product: PRODUCT }} onSave={onSave} />,
    );
    const dialog = screen.getByRole("dialog");

    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Min" }), {
      target: { value: "2" },
    });
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Max" }), {
      target: { value: "9" },
    });
    fireEvent.change(
      within(dialog).getByRole("spinbutton", { name: "Safety stock" }),
      { target: { value: "1" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Notes"), {
      target: { value: "Back shelf" },
    });

    await userEvent.click(
      within(dialog).getByRole("combobox", { name: "Preferred supplier" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "ACME" }));

    fireEvent.click(within(dialog).getByRole("combobox", { name: "Location" }));
    fireEvent.click(await screen.findByText("Cold Storage"));

    await waitFor(() => expect(state().locationId).toBe("loc-1"));
    expect(state()).toMatchObject({
      minQuantity: "2",
      maxQuantity: "9",
      safetyStock: "1",
      notes: "Back shelf",
      preferredPartnerId: "p-1",
    });

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it("picks a product and clears it again", async () => {
    render(<Harness initial={emptyForm} />);
    fireEvent.change(screen.getByLabelText(/^Product/), {
      target: { value: "lat" },
    });
    fireEvent.click(await screen.findByText("Latte cups"));
    await waitFor(() =>
      expect(state().product?.product_template_id).toBe("tpl-1"),
    );
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(state().product).toBeNull();
  });

  it("says when the search found nothing and where the catalogue lives", async () => {
    function Empty() {
      const [form, setForm] = useState(emptyForm);
      return (
        <ReorderRuleFormModal
          open
          form={form}
          onChange={setForm}
          searchProducts={vi.fn().mockResolvedValue([])}
          onProductSelected={vi.fn()}
          partnerOptions={[]}
          onPartnerSearch={vi.fn()}
          partnersLoading={false}
          onSave={vi.fn()}
          onClose={vi.fn()}
          isSaving={false}
        />
      );
    }
    render(<Empty />);
    fireEvent.change(screen.getByLabelText(/^Product/), {
      target: { value: "zzz" },
    });
    expect(await screen.findByText(/zzz/)).toBeInTheDocument();
  });

  it("hands the supplier search to the page and closes on Cancel", async () => {
    const onPartnerSearch = vi.fn();
    const onClose = vi.fn();
    render(
      <Harness
        initial={{ ...emptyForm, id: "rule-1", product: PRODUCT }}
        onPartnerSearch={onPartnerSearch}
        onClose={onClose}
      />,
    );
    // An existing rule keeps its product: no picker to change it.
    expect(screen.queryByLabelText(/^Product/)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("combobox", { name: "Preferred supplier" }),
    );
    await userEvent.type(
      await screen.findByPlaceholderText("Search suppliers…"),
      "Zed",
    );
    await waitFor(() => expect(onPartnerSearch).toHaveBeenCalledWith("Zed"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });
});
