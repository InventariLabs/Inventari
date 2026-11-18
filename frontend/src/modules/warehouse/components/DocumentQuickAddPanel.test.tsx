import { fireEvent, render, screen } from "@/test/utils";
import { describe, expect, it, vi } from "vitest";
import { DocumentQuickAddPanel } from "./DocumentQuickAddPanel";
import { createEmptyQuickAddLineDraft } from "./documentFormShared";

// The UoM select the panel mounts beside the quantity field.
vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useFlatUoms: () => ({
    data: [
      { id: "uom-pcs", name: "Pieces", symbol: "pcs", rounding: "1.000000" },
    ],
  }),
}));

function makeProps() {
  return {
    value: createEmptyQuickAddLineDraft(),
    onChange: vi.fn(),
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
  };
}

function quantityField() {
  return screen.getByRole("spinbutton", { name: /quantity/i });
}

describe("DocumentQuickAddPanel — quantity field", () => {
  // Every change is read as it is: the empty report of the dot step ("12."
  // while the reader types) keeps the quantity empty, so the fraction being
  // typed survives and an emptied field is not saved as a single piece.
  it("reports each complete number and null when the field is emptied", () => {
    const props = makeProps();
    render(<DocumentQuickAddPanel {...props} />);

    fireEvent.change(quantityField(), { target: { value: "2" } });
    expect(props.onChange).toHaveBeenCalledWith({ quantity: 2 });

    fireEvent.change(quantityField(), { target: { value: "" } });
    expect(props.onChange).toHaveBeenCalledWith({ quantity: null });

    fireEvent.change(quantityField(), { target: { value: "2.5" } });
    expect(props.onChange).toHaveBeenCalledWith({ quantity: 2.5 });
  });

  it("does not rewrite the field to one on the dot step's empty report", () => {
    const props = makeProps();
    render(<DocumentQuickAddPanel {...props} />);

    fireEvent.change(quantityField(), { target: { value: "2" } });
    fireEvent.change(quantityField(), { target: { value: "" } });

    expect(quantityField()).toHaveValue(null);
  });
});
