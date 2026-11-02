/**
 * Both document windows ask "how many units of this line?" — the correction
 * with a stepper, the return with a bare number field, for the same concept
 * in two dialogs opened from the same menu.
 */
import { useState } from "react";
import { fireEvent, render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LineQuantityStepper } from "./LineQuantityStepper";

// The unit catalogue the field reads its step from.
const catalogue = vi.hoisted(() => ({ loaded: true }));

vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useFlatUoms: () => ({
    data: !catalogue.loaded
      ? undefined
      : [
          {
            id: "uom-pcs",
            name: "Pieces",
            symbol: "pcs",
            rounding: "1.000000",
          },
          {
            id: "uom-kg",
            name: "Kilogram",
            symbol: "kg",
            rounding: "0.001000",
          },
        ],
  }),
}));

/** The stepper as a window uses it: the value it reports comes back to it. */
function Stateful({ uomId }: { uomId: string }) {
  const [value, setValue] = useState(0);
  return (
    <LineQuantityStepper
      value={value}
      onChange={(next) => {
        if (next !== null) setValue(next);
      }}
      min={0}
      uomId={uomId}
      label="Quantity"
    />
  );
}

describe("LineQuantityStepper", () => {
  it("offers a thumb the touch height on a phone and keeps the desk dense", () => {
    render(
      <LineQuantityStepper value={0} onChange={vi.fn()} label="Quantity" />,
    );

    // The phone's list of goods with no order drew 28px buttons beside the
    // receiving session's 44px stepper. jsdom has no layout, so this pins
    // the classes the screen sizes them by.
    for (const name of [/decrease/i, /increase/i]) {
      expect(screen.getByRole("button", { name })).toHaveClass(
        "h-11",
        "w-11",
        "md:h-10",
        "shrink-0",
      );
    }
    expect(screen.getByRole("spinbutton", { name: "Quantity" })).toHaveClass(
      "h-11",
      "md:h-10",
    );
  });

  it("names the field and both buttons", () => {
    render(
      <LineQuantityStepper value={0} onChange={vi.fn()} label="Quantity" />,
    );

    expect(
      screen.getByRole("spinbutton", { name: "Quantity" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /decrease/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /increase/i }),
    ).toBeInTheDocument();
  });

  it("keeps the buttons inside the bounds typing obeys", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <LineQuantityStepper
        value={3}
        onChange={onChange}
        min={0}
        max={3}
        label="Quantity"
      />,
    );

    expect(screen.getByRole("button", { name: /increase/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /decrease/i }));
    expect(onChange).toHaveBeenCalledWith(2);
  });

  // 1.5 was typed into a correction on a line counted in pieces, shown as
  // "+1.5", saved, confirmed and executed. The field reported `stepMismatch`
  // the whole time and nothing read it.
  it("says why a fraction does not fit a unit counted in whole numbers", async () => {
    const user = userEvent.setup();
    render(<Stateful uomId="uom-pcs" />);

    const field = screen.getByRole("spinbutton", { name: "Quantity" });
    expect(field).toHaveAttribute("step", "1");
    expect(field).not.toHaveAttribute("aria-invalid", "true");

    await user.type(field, "1.5");
    expect(field).toHaveAttribute("aria-invalid", "true");
  });

  it("takes a fraction the unit does count in", async () => {
    const user = userEvent.setup();
    render(<Stateful uomId="uom-kg" />);

    const field = screen.getByRole("spinbutton", { name: "Quantity" });
    expect(field).toHaveAttribute("step", "0.001");

    await user.type(field, "1.5");
    expect(field).not.toHaveAttribute("aria-invalid", "true");
  });

  // Right after a scan the unit catalogue may not have answered yet: the
  // permissive fallback step (0.001) made the first tap count 1.001.
  it("moves by one until the unit has answered", async () => {
    catalogue.loaded = false;
    try {
      const user = userEvent.setup();
      const onChange = vi.fn();
      render(
        <LineQuantityStepper
          value={1}
          onChange={onChange}
          uomId="uom-pcs"
          label="Quantity"
        />,
      );

      await user.click(screen.getByRole("button", { name: /increase/i }));
      expect(onChange).toHaveBeenCalledWith(2);
    } finally {
      catalogue.loaded = true;
    }
  });

  it("moves by the unit's step, not by one", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <LineQuantityStepper
        value={1}
        onChange={onChange}
        uomId="uom-kg"
        label="Quantity"
      />,
    );

    await user.click(screen.getByRole("button", { name: /increase/i }));
    expect(onChange).toHaveBeenCalledWith(1.001);
  });

  // While "12.5" is typed, the number field reports the dot step
  // as "" — the stepper used to answer that with Number("") === 0, the
  // field rewrote itself to "0", and the correction got 5 instead of 12.5.
  it("does not drop the quantity to zero on the dot step's empty report", () => {
    const onChange = vi.fn();
    render(
      <LineQuantityStepper
        value={12}
        onChange={onChange}
        uomId="uom-kg"
        label="Quantity"
      />,
    );

    const field = screen.getByRole("spinbutton", { name: "Quantity" });
    fireEvent.change(field, { target: { value: "" } });
    expect(field).toHaveValue(null);
    expect(onChange).not.toHaveBeenCalledWith(0);

    fireEvent.change(field, { target: { value: "12.5" } });
    expect(onChange).toHaveBeenCalledWith(12.5);
  });
});
