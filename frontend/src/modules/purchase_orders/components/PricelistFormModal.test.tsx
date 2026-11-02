import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import {
  PricelistFormModal,
  emptyForm,
  type PricelistFormState,
} from "./PricelistFormModal";

const noop = vi.fn();

function renderModal(form: PricelistFormState = emptyForm, onSave = vi.fn()) {
  render(
    <PricelistFormModal
      open
      form={form}
      onChange={noop}
      searchProducts={vi.fn().mockResolvedValue([])}
      onProductSelected={noop}
      onSave={onSave}
      onClose={noop}
      isSaving={false}
    />,
  );
  return onSave;
}

const saveButton = () => screen.getByRole("button", { name: "Save" });

/**
 * The blank entry's `valid_from` is not a display value — it is saved, so it
 * has to be the reader's own day. `toISOString()` answers in UTC, which
 * between midnight and the zone offset is yesterday or tomorrow.
 */
describe("PricelistFormModal — the default valid_from day", () => {
  it("prefills the reader's own day, not the UTC one", async () => {
    const original = process.env.TZ;
    process.env.TZ = "Europe/Warsaw";
    vi.useFakeTimers();
    // 00:30 on 11 September 2026 local is still 22:30 on the 10th in UTC.
    vi.setSystemTime(new Date(2026, 8, 11, 0, 30));
    try {
      vi.resetModules();
      const fresh = await import("./PricelistFormModal");
      expect(fresh.emptyForm.validFrom).toBe("2026-09-11");
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
    }
  });
});

describe("PricelistFormModal validation", () => {
  it("blocks save and flags a missing unit price", async () => {
    const onSave = renderModal();
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText("Price must be greater than 0"),
    ).toBeInTheDocument();
    // The required field carries the marker the API enforces — `aria-required`
    // on the control and a star outside the accessible name: the
    // role query matches by computed name, which the hidden star never joins.
    expect(screen.getByRole("spinbutton", { name: "Price" })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("blocks save and flags a zero unit price", async () => {
    const onSave = renderModal({ ...emptyForm, unitPrice: "0" });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText("Price must be greater than 0"),
    ).toBeInTheDocument();
  });

  it("blocks save and flags a non-positive min quantity", async () => {
    const onSave = renderModal({
      ...emptyForm,
      unitPrice: "10",
      minQuantity: "0",
    });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText("Min qty must be greater than 0"),
    ).toBeInTheDocument();
  });

  it("blocks save when valid_to is before valid_from", async () => {
    const onSave = renderModal({
      ...emptyForm,
      unitPrice: "10",
      validFrom: "2026-08-25",
      validTo: "2026-08-20",
    });
    await userEvent.click(saveButton());

    expect(onSave).not.toHaveBeenCalled();
    expect(
      screen.getByText("Valid to must be on or after valid from"),
    ).toBeInTheDocument();
  });

  it("calls onSave when every API rule is satisfied", async () => {
    const onSave = renderModal({ ...emptyForm, unitPrice: "10" });
    await userEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("offers currency from a dictionary instead of free text", () => {
    renderModal({ ...emptyForm, unitPrice: "10" });

    const currencyField = screen.getByLabelText("Currency");
    expect(currencyField.tagName).toBe("SELECT");
    expect(screen.getByRole("option", { name: /PLN/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /currency/i })).toBeNull();
  });
});
