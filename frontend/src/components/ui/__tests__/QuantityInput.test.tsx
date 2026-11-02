import { useState } from "react";
import { fireEvent, render, screen } from "@/test/utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuantityInput } from "@/components/ui/QuantityInput";
import type { UomPrecision } from "@/hooks/useUomPrecision";

const mockPrecision: { current: UomPrecision } = {
  current: {
    stepString: "any",
    step: 0.001,
    min: 0.001,
    isInteger: false,
    decimalPlaces: 3,
  },
};

vi.mock("@/hooks/useUomPrecision", async (importOriginal) => ({
  // The message helper is the real one — what is stubbed here is the
  // catalogue lookup, not the rule the unit's step states.
  ...(await importOriginal<object>()),
  useUomPrecision: () => mockPrecision.current,
  useUomPrecisionBySymbol: () => mockPrecision.current,
}));

function getInput() {
  return screen.getByRole("spinbutton");
}

describe("QuantityInput (min/step per UoM)", () => {
  afterEach(() => {
    mockPrecision.current = {
      stepString: "any",
      step: 0.001,
      min: 0.001,
      isInteger: false,
      decimalPlaces: 3,
    };
  });

  it("uses precision.min as the HTML min attribute (not hardcoded 0)", () => {
    mockPrecision.current = {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };

    render(
      <QuantityInput uomId="uom-1" value="" onChange={() => {}} label="Qty" />,
    );

    expect(getInput()).toHaveAttribute("min", "1");
  });

  it("shows a step-alignment error for fractional UoM when value is not a multiple of step", () => {
    mockPrecision.current = {
      stepString: "0.5",
      step: 0.5,
      min: 0.5,
      isInteger: false,
      decimalPlaces: 1,
    };

    render(
      <QuantityInput uomId="uom-1" value="" onChange={() => {}} label="Qty" />,
    );

    fireEvent.change(getInput(), { target: { value: "1.3" } });

    expect(screen.getByText(/multiple of 0\.5/i)).toBeInTheDocument();
  });

  it("announces a value it was given that its own min forbids", () => {
    // An imported line arrives at -5 in a field whose min is 0.001. The
    // browser knows the sentence and nobody was shown it: the check ran
    // only while somebody typed, so aria-invalid stayed unset.
    render(
      <QuantityInput
        uomId="uom-1"
        value="-5"
        onChange={() => {}}
        label="Qty"
      />,
    );

    expect(getInput()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/at least 0\.001/i)).toBeInTheDocument();
  });

  it("says nothing about a value it was given that fits the unit", () => {
    render(
      <QuantityInput uomId="uom-1" value="2" onChange={() => {}} label="Qty" />,
    );

    expect(getInput()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("shows a min error when value is below precision.min", () => {
    mockPrecision.current = {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };

    render(
      <QuantityInput uomId="uom-1" value="" onChange={() => {}} label="Qty" />,
    );

    fireEvent.change(getInput(), { target: { value: "0" } });

    expect(screen.getByText(/at least 1/i)).toBeInTheDocument();
  });

  it("lets a field state a floor of its own, and announces that one instead", () => {
    // The execution screen counts nothing-received-yet as zero, which the
    // unit refuses everywhere a quantity is entered. A field whose own
    // domain reaches lower says so, and then the attribute and the sentence
    // have to agree -- an input declaring min="0" while announcing "must be
    // at least 0.001" is the screen contradicting itself.
    render(
      <QuantityInput
        uomId="uom-1"
        min={0}
        value="0"
        onChange={() => {}}
        label="Qty"
      />,
    );

    expect(getInput()).toHaveAttribute("min", "0");
    expect(getInput()).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/at least/i)).not.toBeInTheDocument();
  });

  it("still refuses what falls under a floor the field set itself", () => {
    render(
      <QuantityInput
        uomId="uom-1"
        min={0}
        value="-5"
        onChange={() => {}}
        label="Qty"
      />,
    );

    expect(getInput()).toHaveAttribute("aria-invalid", "true");
    // The field's floor, not the unit's: "at least 0.001" here would mean the
    // prop reached the attribute and not the sentence.
    expect(screen.getByText("Must be at least 0")).toBeInTheDocument();
  });

  it("drops the sentence about a typed value once the field no longer holds it", () => {
    // A panel may clamp what was typed — a line that can still receive two
    // takes 2, not the 2.5 somebody entered. The sentence belonged to the
    // 2.5, and it used to stay hanging over the 2.
    mockPrecision.current = {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };

    function Clamping() {
      const [value, setValue] = useState<number | "">("");
      return (
        <QuantityInput
          uomId="uom-1"
          value={value}
          onChange={(e) => setValue(Math.min(Number(e.target.value), 2))}
          label="Qty"
        />
      );
    }

    render(<Clamping />);
    fireEvent.change(getInput(), { target: { value: "2.5" } });

    expect(getInput()).toHaveValue(2);
    expect(screen.queryByText(/whole numbers only/i)).not.toBeInTheDocument();
  });

  it("drops the sentence when a button, not the keyboard, sets the value", () => {
    // The execution panel changes the field from outside: Clear writes 0,
    // +1 steps, "Fill to plan" jumps to the planned quantity. None of them
    // goes through the field's own `onChange`, so the sentence about the
    // last typed text used to sit over a value nobody typed — "Clear" gave
    // zero and the field went on calling zero a non-integer.
    mockPrecision.current = {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };

    function WithClearButton() {
      const [value, setValue] = useState<number | string>("");
      return (
        <>
          <QuantityInput
            uomId="uom-1"
            min={0}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            label="Qty"
          />
          <button type="button" onClick={() => setValue(0)}>
            Clear
          </button>
        </>
      );
    }

    render(<WithClearButton />);
    fireEvent.change(getInput(), { target: { value: "0.5" } });
    expect(screen.getByText(/whole numbers only/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(getInput()).toHaveValue(0);
    expect(screen.queryByText(/whole numbers only/i)).not.toBeInTheDocument();
    expect(getInput()).not.toHaveAttribute("aria-invalid", "true");
  });
});

describe("QuantityInput (committed values through onQuantityChange)", () => {
  // A number input reports the incomplete "12." as "" while the reader is
  // still typing. The caller that fed Number("") of that report
  // into a numeric state wrote 0 back into the controlled field, and the
  // dot died with it: "12.5" ended as "05", quantity 5. The committed-value
  // API keeps the typing inside the field: the caller is handed a number
  // when the text is one and null while it is not, and never sees a text
  // worth casting.
  //
  // The events here carry the values the browser reports, one per keystroke
  // of "12.5": "1", "12", "" (the dot), "12.5".
  afterEach(() => {
    mockPrecision.current = {
      stepString: "any",
      step: 0.001,
      min: 0.001,
      isInteger: false,
      decimalPlaces: 3,
    };
  });

  it("reports each complete number and null for the transient empty", () => {
    const onQuantityChange = vi.fn();
    render(
      <QuantityInput
        uomId="uom-1"
        value={0}
        onQuantityChange={onQuantityChange}
        label="Qty"
      />,
    );

    const input = getInput();
    fireEvent.change(input, { target: { value: "1" } });
    expect(onQuantityChange).toHaveBeenLastCalledWith(1);
    fireEvent.change(input, { target: { value: "12" } });
    expect(onQuantityChange).toHaveBeenLastCalledWith(12);
    fireEvent.change(input, { target: { value: "" } });
    expect(onQuantityChange).toHaveBeenLastCalledWith(null);
    fireEvent.change(input, { target: { value: "12.5" } });
    expect(onQuantityChange).toHaveBeenLastCalledWith(12.5);
  });

  it("keeps the field at the reader's place on the transient empty, not at zero", () => {
    render(
      <QuantityInput
        uomId="uom-1"
        value={12}
        onQuantityChange={() => {}}
        label="Qty"
      />,
    );

    fireEvent.change(getInput(), { target: { value: "" } });

    // jest-dom reads an empty number field as null — the field holds no
    // number, which is exactly the point.
    expect(getInput()).toHaveValue(null);
  });

  it("treats a typed zero as a number the field holds, not as a missing value", () => {
    const onQuantityChange = vi.fn();
    render(
      <QuantityInput
        uomId="uom-1"
        value={5}
        onQuantityChange={onQuantityChange}
        label="Qty"
      />,
    );

    fireEvent.change(getInput(), { target: { value: "0" } });

    expect(onQuantityChange).toHaveBeenLastCalledWith(0);
  });

  it("gives the field back its committed value on blur", () => {
    render(
      <QuantityInput
        uomId="uom-1"
        value={7}
        onQuantityChange={() => {}}
        label="Qty"
      />,
    );

    fireEvent.change(getInput(), { target: { value: "" } });
    fireEvent.blur(getInput());

    expect(getInput()).toHaveValue(7);
  });

  it("validates the text being typed, and stops once blur returns the value", () => {
    mockPrecision.current = {
      stepString: "1",
      step: 1,
      min: 1,
      isInteger: true,
      decimalPlaces: 0,
    };
    render(
      <QuantityInput
        uomId="uom-1"
        value={2}
        onQuantityChange={() => {}}
        label="Qty"
      />,
    );

    fireEvent.change(getInput(), { target: { value: "1.5" } });
    expect(screen.getByText(/whole numbers only/i)).toBeInTheDocument();

    fireEvent.blur(getInput());
    expect(screen.queryByText(/whole numbers only/i)).not.toBeInTheDocument();
    expect(getInput()).toHaveValue(2);
  });
});
