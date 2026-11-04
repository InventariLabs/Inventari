import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { withLanguage } from "@/test/mocks/i18n";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";
import {
  ReorderRuleFormModal,
  emptyForm,
  type RuleFormState,
} from "./ReorderRuleFormModal";

const noop = vi.fn();

function renderModal(form: RuleFormState = emptyForm, onSave = vi.fn()) {
  render(
    <ReorderRuleFormModal
      open
      form={form}
      onChange={noop}
      searchProducts={vi.fn().mockResolvedValue([])}
      onProductSelected={noop}
      partnerOptions={[{ id: "p-1", name: "ACME" }]}
      onPartnerSearch={vi.fn()}
      partnersLoading={false}
      onSave={onSave}
      onClose={noop}
      isSaving={false}
    />,
  );
  return onSave;
}

const saveButton = () => screen.getByRole("button", { name: "Save" });

const milk: CatalogueSearchResult = {
  product_template_id: "tpl-1",
  name: "Milk",
  sku: null,
  barcode: null,
  brand: null,
  uom_id: "uom-1",
  uom_symbol: "pcs",
  image_url: null,
  is_stub: false,
};

describe("ReorderRuleFormModal validation", () => {
  it("blocks save and flags a missing max quantity", async () => {
    const onSave = renderModal();
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Max must be greater than 0")).toBeInTheDocument();
    // The required field carries the marker the API enforces — `aria-required`
    // on the control and a star outside the accessible name: the
    // role query matches by computed name, which the hidden star never joins.
    expect(screen.getByRole("spinbutton", { name: "Max" })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("blocks save and flags a zero max quantity", async () => {
    const onSave = renderModal({ ...emptyForm, maxQuantity: "0" });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Max must be greater than 0")).toBeInTheDocument();
  });

  it("blocks save and flags a missing min quantity", async () => {
    // MIN is the threshold that makes the rule fire; MAX is only the level to
    // reach. The star sat on MAX alone, so a rule saved with the required
    // fields got MIN 0 and the engine skipped it outright — a row on the list
    // that looked like every other one and could never produce an alert.
    const onSave = renderModal({ ...emptyForm, maxQuantity: "20" });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Min must be greater than 0 — it is the threshold that makes the rule fire",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Min" })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("blocks save and flags a zero min quantity", async () => {
    const onSave = renderModal({
      ...emptyForm,
      minQuantity: "0",
      maxQuantity: "20",
    });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Min must be greater than 0 — it is the threshold that makes the rule fire",
      ),
    ).toBeInTheDocument();
  });

  it("calls onSave once both thresholds are above 0", async () => {
    const onSave = renderModal({
      ...emptyForm,
      product: milk,
      minQuantity: "5",
      maxQuantity: "20",
    });
    await userEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("blocks save without a product and says so on the product field", async () => {
    const onSave = renderModal({
      ...emptyForm,
      minQuantity: "5",
      maxQuantity: "20",
    });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Select a product first")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /Product/ })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("blocks a max below the min and puts the sentence on the Max field", async () => {
    const onSave = renderModal({
      ...emptyForm,
      product: milk,
      minQuantity: "10",
      maxQuantity: "5",
    });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    const message = screen.getByText("Max (5) cannot be below min (10)");
    expect(screen.getByRole("spinbutton", { name: "Max" })).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining(message.id),
    );
    expect(message.textContent).not.toMatch(/_/);
  });

  it("shows a description for each threshold field", () => {
    renderModal();

    expect(
      screen.getByText("Reorder when available stock drops below this amount."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Target stock level after replenishment."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Safety stock kept in reserve; stock never falls below this.",
      ),
    ).toBeInTheDocument();
  });

  it("localizes the selected product unit on all three threshold fields", async () => {
    const product: CatalogueSearchResult = {
      product_template_id: "tpl-1",
      name: "Milk",
      sku: null,
      barcode: null,
      brand: null,
      uom_id: "uom-1",
      uom_symbol: "pcs",
      image_url: null,
      is_stub: false,
    };
    await withLanguage("pl", () => {
      renderModal({ ...emptyForm, product });

      expect(screen.getAllByText("szt.")).toHaveLength(3);
      expect(screen.queryByText("pcs")).not.toBeInTheDocument();
    });
  });

  it("omits the unit when no product is selected", () => {
    renderModal();

    expect(screen.queryByText("pcs")).not.toBeInTheDocument();
  });

  it("lines the three threshold fields up on shared rows", () => {
    // jsdom has no layout, so this pins the classes that make it: one grid,
    // each field spanning its label / input / description / error rows. The
    // old grid aligned column bottoms (items-end), so a wrapped label lowered
    // only its own input.
    renderModal();

    const field = (name: string | RegExp) =>
      screen
        .getByRole("spinbutton", { name })
        .closest("div.grid") as HTMLElement;
    for (const name of ["Min", "Max", /safety/i]) {
      expect(field(name)).toHaveClass("grid-rows-subgrid", "row-span-4");
    }
    const row = field("Min").parentElement as HTMLElement;
    expect(row).toHaveClass("grid-cols-3");
    expect(row).toHaveClass("items-stretch");
    expect(row).not.toHaveClass("items-end");
  });
});
