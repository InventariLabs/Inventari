import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ShortageModal } from "./ShortageModal";
import { withLanguage } from "@/test/mocks/i18n";
import type { ShortageEntry } from "@/modules/maker/types/maker";

const shortage: ShortageEntry = {
  child_template_id: "tpl-flour",
  child_template_name: "Flour",
  needed: "5.000000",
  available: "0",
  shortage: "5.000000",
  uom_symbol: "kg",
  convertible: true,
};

function renderModal(
  props: Partial<React.ComponentProps<typeof ShortageModal>> = {},
) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ShortageModal
      open
      variant="warning"
      shortages={[shortage]}
      canConfirm
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onConfirm, onCancel };
}

describe("ShortageModal", () => {
  it("WARN variant offers a working confirm button", () => {
    const { onConfirm } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Create anyway" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("BLOCK variant hides the confirm button", () => {
    renderModal({ variant: "danger", canConfirm: false, onConfirm: undefined });
    expect(
      screen.queryByRole("button", { name: "Create anyway" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Cannot create — ingredients missing"),
    ).toBeInTheDocument();
    // The hint appears exactly once (no duplication).
    expect(
      screen.getAllByText(
        "Restock these ingredients or switch the shortage strategy in settings.",
      ),
    ).toHaveLength(1);
  });

  it("formats decimal quantities without trailing zeros", () => {
    renderModal();
    const cells = screen.getAllByText(/^5 kg$/);
    // needed + short cells both render "5 kg" (not "5.000000 kg")
    expect(cells.length).toBe(2);
  });

  it("writes pcs the way the interface writes it, not the way the wire does", async () => {
    // The modal shared the preview's old habit of printing the raw symbol:
    // a Polish flow said "20 pcs" where the shelf said "20 SZT.". "kg"
    // passes unitLabel untouched, so this pins the translation itself.
    await withLanguage("pl", () => {
      renderModal({
        shortages: [
          {
            ...shortage,
            uom_symbol: "pcs",
            needed: "22000.000",
            shortage: "20000.000",
          },
        ],
      });

      expect(screen.getByText("22 000 szt.")).toBeInTheDocument();
      expect(screen.getByText("20 000 szt.")).toBeInTheDocument();
      // The raw symbol must not come back, and the thousands are grouped
      // the way the reader's language groups them.
      expect(screen.queryByText(/pcs/)).not.toBeInTheDocument();
      expect(screen.queryByText(/22000/)).not.toBeInTheDocument();
    });
  });

  it("shows the unit-mismatch hint for non-convertible entries", () => {
    renderModal({ shortages: [{ ...shortage, convertible: false }] });
    expect(screen.getByText("unit mismatch")).toBeInTheDocument();
  });

  it("supports title/hint overrides (complete-time shortage)", () => {
    renderModal({
      variant: "danger",
      canConfirm: false,
      title: "Cannot complete — insufficient stock",
      hint: "These ingredients ran out since the draft was created.",
    });
    expect(
      screen.getByText("Cannot complete — insufficient stock"),
    ).toBeInTheDocument();
  });
});
