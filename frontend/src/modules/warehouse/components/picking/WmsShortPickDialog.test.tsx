import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import WmsShortPickDialog from "./WmsShortPickDialog";
import type { WmsPickLine } from "@/modules/warehouse/api/documents";

const line: WmsPickLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "pending",
  picked_quantity: 0,
  bin_location: null,
  product_name: "Widget",
  lot_name: null,
  expected_quantity: 3,
  uom_symbol: "pcs",
};

function renderDialog(
  overrides: Partial<Parameters<typeof WmsShortPickDialog>[0]> = {},
) {
  return render(
    <WmsShortPickDialog
      line={line}
      isLoading={false}
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      {...overrides}
    />,
  );
}

async function confirmPick(qty: string, code?: string, note?: string) {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  renderDialog({ onConfirm });

  const field = screen.getByRole("spinbutton", {
    name: "Final picked quantity",
  });
  await user.clear(field);
  await user.type(field, qty);
  if (code) {
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Discrepancy" }),
      code,
    );
  }
  if (note) {
    await user.type(screen.getByLabelText("What happened"), note);
  }
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  return onConfirm;
}

describe("WmsShortPickDialog", () => {
  it("announces itself as a named dialog", () => {
    renderDialog();

    expect(screen.getByRole("dialog", { name: "Short pick" })).toBeVisible();
  });

  it("names its quantity field as the final total", () => {
    renderDialog();

    expect(
      screen.getByRole("spinbutton", { name: "Final picked quantity" }),
    ).toBeVisible();
  });

  it("shows what was expected, what was scanned and what is left", () => {
    renderDialog({ line: { ...line, picked_quantity: 2 } });

    expect(
      screen.getByText("Expected 3 pcs. · scanned 2 pcs. · remaining 1 pcs."),
    ).toBeVisible();
  });

  it("prefills the field with the scanned quantity", () => {
    renderDialog({ line: { ...line, picked_quantity: 2 } });

    expect(
      screen.getByRole("spinbutton", { name: "Final picked quantity" }),
    ).toHaveValue(2);
  });

  it("closes on Escape, like every other sheet", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderDialog({ onCancel });

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalled();
  });

  it("records the picked quantity under the chosen discrepancy code", async () => {
    const onConfirm = await confirmPick("2", "DAMAGE");

    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      2,
      "DAMAGE",
      undefined,
      false,
    );
  });

  it("offers only reasons that can explain a short pick", async () => {
    const user = userEvent.setup();
    renderDialog({ onConfirm: vi.fn() });
    const field = screen.getByRole("spinbutton", {
      name: "Final picked quantity",
    });
    await user.clear(field);
    await user.type(field, "2");

    const options = within(
      screen.getByRole("combobox", { name: "Discrepancy" }),
    )
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual(["Shortage", "Damage", "Quality hold", "Other"]);
  });

  it("refuses a total below the scans until the count says it replaces them", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderDialog({ onConfirm, line: { ...line, picked_quantity: 2 } });

    const field = screen.getByRole("spinbutton", {
      name: "Final picked quantity",
    });
    await user.clear(field);
    await user.type(field, "1");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The final quantity cannot be below the scanned quantity",
    );
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("checkbox", {
        name: "This count replaces the scanned quantity",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      1,
      "SHORTAGE",
      undefined,
      true,
    );
  });

  it("asks what happened when the reason is Other and none was given", async () => {
    const onConfirm = await confirmPick("1", "OTHER");

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Say what happened, or pick a different reason",
    );
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent
      .setup()
      .type(screen.getByLabelText("What happened"), "wrong item");
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      1,
      "OTHER",
      "wrong item",
      false,
    );
  });

  it("a full pick carries no discrepancy", async () => {
    const onConfirm = await confirmPick("3");

    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      3,
      undefined,
      undefined,
      false,
    );
  });

  it("offers no Skip of its own — the row owns skipping", () => {
    renderDialog();

    expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
  });
});
