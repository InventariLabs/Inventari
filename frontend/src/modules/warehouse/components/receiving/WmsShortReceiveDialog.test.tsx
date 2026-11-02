import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import WmsShortReceiveDialog from "./WmsShortReceiveDialog";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";

const line: WmsReceiveLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  from_order: false,
  pick_order: 1,
  status: "pending",
  received_quantity: 0,
  product_name: "Widget",
  lot_name: null,
  expected_quantity: 3,
  uom_symbol: "pcs",
};

describe("WmsShortReceiveDialog", () => {
  it("records a quantity above expected with the surplus reason", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "5");

    expect(screen.getByText("Discrepancy")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      5,
      "SURPLUS",
      undefined,
      false,
      0,
    );
  });

  it("does not require a discrepancy code for a full receive", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "3");

    expect(screen.queryByText("Discrepancy")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      3,
      "",
      undefined,
      false,
      0,
    );
  });

  it("asks for a discrepancy code on a partial receive", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "2");

    expect(screen.getByText("Discrepancy")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      2,
      "SHORTAGE",
      undefined,
      false,
      0,
    );
  });

  it("shows what was expected, what was scanned and what is left", () => {
    render(
      <WmsShortReceiveDialog
        line={{ ...line, received_quantity: 2 }}
        isLoading={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        /expected 3 pcs\. · scanned 2 pcs\. · remaining 1 pcs\./,
      ),
    ).toBeVisible();
  });

  it("prefills the field with the scanned quantity", () => {
    render(
      <WmsShortReceiveDialog
        line={{ ...line, received_quantity: 2 }}
        isLoading={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    ).toHaveValue(2);
  });

  it("says what was expected with nothing standing where the unit would", () => {
    // The line was written by hand and carries no unit. The sentence has a
    // slot for one, and filling it with a dash printed "expected 1 —" — a
    // quantity dressed as a measurement the line cannot back.
    render(
      <WmsShortReceiveDialog
        line={{ ...line, uom_symbol: null }}
        isLoading={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/expected 3 · scanned 0 · remaining 3/),
    ).toBeVisible();
    expect(screen.queryByText(/expected 3 —/)).toBeNull();
  });

  it("records a quantity of zero as nothing arrived", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "0");

    await user.click(screen.getByRole("button", { name: "Confirm" }));

    // Nothing arrived on this line is an answer, not an omission: the
    // dialog used to refuse zero with "Enter how much actually arrived".
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      0,
      "SHORTAGE",
      undefined,
      false,
      0,
    );
  });

  it("refuses an empty field", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.clear(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter how much actually arrived",
    );
  });

  it("refuses a total below the scans until the count says it replaces them", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, received_quantity: 2 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "1");
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
      0,
    );
  });

  it("asks what happened when the discrepancy is 'Other'", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.clear(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    );
    await user.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "2",
    );
    await user.selectOptions(screen.getByRole("combobox"), "OTHER");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Say what happened, or pick a different reason",
    );

    await user.type(screen.getByTestId("short-receive-note"), "pallet soaked");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      2,
      "OTHER",
      "pallet soaked",
      false,
      0,
    );
  });

  it("does not ask for a note for a named discrepancy", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.clear(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    );
    await user.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "2",
    );

    expect(screen.queryByTestId("short-receive-note")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      2,
      "SHORTAGE",
      undefined,
      false,
      0,
    );
  });
});

describe("WmsShortReceiveDialog — one verb per question", () => {
  it("does not offer skipping a second time", () => {
    // Skipping a line is the row's own action, with an icon beside the line
    // it skips. This dialog exists to record what actually arrived.
    render(
      <WmsShortReceiveDialog
        line={line}
        isLoading={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /skip/i }),
    ).not.toBeInTheDocument();
  });
});

describe("WmsShortReceiveDialog — a delivery that arrived damaged in full", () => {
  it("says a quarantine code on a short line explains the gap, not the goods that arrived", async () => {
    const user = userEvent.setup();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10 }}
        isLoading={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await user.clear(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    );
    await user.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "7",
    );
    await user.selectOptions(screen.getByRole("combobox"), "DAMAGE");

    // Seven arrived, three never did. Picking Damage here explains the three;
    // it must not be read as a decision about the seven in hand.
    expect(
      screen.getByText(
        "This explains the difference from the expected quantity. It does not quarantine what arrived — enter that quantity above to hold it back.",
      ),
    ).toBeVisible();
  });

  it("records the whole received quantity as quarantined in one answer", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.clear(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
    );
    await user.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "10",
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "All received goods are quarantined",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      10,
      "DAMAGE",
      undefined,
      false,
      10,
    );
  });

  it("keeps the whole-quantity hold on the count that was typed", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const qtyInput = screen.getByRole("spinbutton", {
      name: "Final received quantity",
    });
    await user.clear(qtyInput);
    await user.type(qtyInput, "7");
    await user.click(
      screen.getByRole("checkbox", {
        name: "All received goods are quarantined",
      }),
    );
    await user.clear(qtyInput);
    await user.type(qtyInput, "9");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    // The count is the answer to "how much arrived"; "all of it is damaged"
    // follows it, so changing the count changes the quarantined quantity too.
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      9,
      "DAMAGE",
      undefined,
      false,
      9,
    );
  });
});

describe("WmsShortReceiveDialog — what was received is not all usable", () => {
  it("sends the held quantity with a reason that means held goods", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10, received_quantity: 7 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const heldInput = screen.getByRole("spinbutton", {
      name: "Quarantined (damaged or quality hold)",
    });
    await user.clear(heldInput);
    await user.type(heldInput, "3");

    // The reason choices narrow to the codes a held quantity can carry.
    expect(screen.queryByText("Shortage")).toBeNull();
    expect(screen.getByText("Damage")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      7,
      "DAMAGE",
      undefined,
      false,
      3,
    );
  });

  it("drops a gap-only reason once goods are held, on screen and in what it sends", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10, received_quantity: 7 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox"), "SHORTAGE");
    const heldInput = screen.getByRole("spinbutton", {
      name: "Quarantined (damaged or quality hold)",
    });
    await user.clear(heldInput);
    await user.type(heldInput, "3");

    // Shortage cannot carry a held quantity, so the field and the request
    // both move to the reason the field now shows.
    expect(screen.getByRole("combobox")).toHaveValue("DAMAGE");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      7,
      "DAMAGE",
      undefined,
      false,
      3,
    );
  });

  it("sends the reason it shows when the whole count is quarantined after a gap reason", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10, received_quantity: 7 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox"), "DAMAGE");
    await user.selectOptions(screen.getByRole("combobox"), "SHORTAGE");
    await user.click(
      screen.getByRole("checkbox", {
        name: "All received goods are quarantined",
      }),
    );

    expect(screen.getByRole("combobox")).toHaveValue("DAMAGE");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      7,
      "DAMAGE",
      undefined,
      false,
      7,
    );
  });

  it("keeps a held reason the worker chose when the hold is cleared again", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10, received_quantity: 7 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const allHeld = screen.getByRole("checkbox", {
      name: "All received goods are quarantined",
    });
    await user.click(allHeld);
    await user.selectOptions(screen.getByRole("combobox"), "QUALITY_HOLD");
    await user.click(allHeld);

    // Quality hold explains a gap too, so the deliberate choice stands.
    expect(screen.getByRole("combobox")).toHaveValue("QUALITY_HOLD");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(
      "line-1",
      7,
      "QUALITY_HOLD",
      undefined,
      false,
      0,
    );
  });

  it("refuses a held quantity above the counted total", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <WmsShortReceiveDialog
        line={{ ...line, expected_quantity: 10, received_quantity: 7 }}
        isLoading={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const heldInput = screen.getByRole("spinbutton", {
      name: "Quarantined (damaged or quality hold)",
    });
    await user.clear(heldInput);
    await user.type(heldInput, "8");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(
      screen.getByText(
        "The quarantined quantity cannot exceed the received quantity.",
      ),
    ).toBeVisible();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
