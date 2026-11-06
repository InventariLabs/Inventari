import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";

import {
  PricelistFormModal,
  emptyForm as emptyPricelistForm,
} from "./PricelistFormModal";
import {
  ReorderRuleFormModal,
  emptyForm as emptyRuleForm,
} from "./ReorderRuleFormModal";

/**
 * Both form windows of this module were plain divs: no dialog role, Escape
 * did nothing, Tab walked out onto the page behind them, and not one field
 * carried a programmatic label. They are the only two modals in the trade
 * modules that did not go through the shared Sheet.
 */

function renderPricelist(onClose = vi.fn()) {
  render(
    <PricelistFormModal
      open
      form={emptyPricelistForm()}
      onChange={vi.fn()}
      searchProducts={vi.fn().mockResolvedValue([])}
      onProductSelected={vi.fn()}
      onSave={vi.fn()}
      onClose={onClose}
      isSaving={false}
    />,
  );
  return onClose;
}

function renderReorderRule(onClose = vi.fn()) {
  render(
    <ReorderRuleFormModal
      open
      form={emptyRuleForm}
      onChange={vi.fn()}
      searchProducts={vi.fn().mockResolvedValue([])}
      onProductSelected={vi.fn()}
      partnerOptions={[{ id: "p-1", name: "ACME" }]}
      onPartnerSearch={vi.fn()}
      partnersLoading={false}
      onSave={vi.fn()}
      onClose={onClose}
      isSaving={false}
    />,
  );
  return onClose;
}

describe("PricelistFormModal accessibility", () => {
  it("announces itself as a named dialog", () => {
    renderPricelist();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName();
  });

  it("closes on Escape", () => {
    const onClose = renderPricelist();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("gives every data field a programmatic label", () => {
    renderPricelist();
    for (const name of [
      "Price",
      "Currency",
      "Min qty",
      "Valid from",
      "Valid to",
      "Notes",
    ]) {
      expect(
        screen.getByLabelText(new RegExp(`^${name}\\s*\\*?$`, "i")),
        `field "${name}" has no accessible name`,
      ).toBeInTheDocument();
    }
  });
});

describe("ReorderRuleFormModal accessibility", () => {
  it("announces itself as a named dialog", () => {
    renderReorderRule();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName();
  });

  it("closes on Escape", () => {
    const onClose = renderReorderRule();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("gives every data field a programmatic label", () => {
    renderReorderRule();
    for (const name of ["Min", "Max", "Safety stock", "Notes"]) {
      expect(
        screen.getByLabelText(new RegExp(`^${name}\\s*\\*?$`, "i")),
        `field "${name}" has no accessible name`,
      ).toBeInTheDocument();
    }
  });
});
