import { act, fireEvent, render, screen } from "@/test/utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { lookupProductByBarcode } from "@/modules/shared/lib/productLookup";
import { DocumentQuickAddPanel } from "./DocumentQuickAddPanel";
import { createEmptyQuickAddLineDraft } from "./documentFormShared";

vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useFlatUoms: () => ({
    data: [
      { id: "uom-pcs", name: "Pieces", symbol: "pcs", rounding: "1.000000" },
    ],
  }),
}));

// The select itself has its own tests; here only its answer matters.
vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: ({
    onChange,
  }: {
    onChange: (id: string, uom: { id: string }) => void;
  }) => (
    <button type="button" onClick={() => onChange("uom-kg", { id: "uom-kg" })}>
      pick kg
    </button>
  ),
}));

// The calendar has its own tests; here only the date it reports matters.
vi.mock("@/components/ui/DateInput", () => ({
  DateInput: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <label>
      {label}
      <input value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  ),
}));

vi.mock("@/modules/shared/lib/productLookup", () => ({
  lookupProductByBarcode: vi.fn(),
}));

function makeProps(
  over: Partial<ReturnType<typeof createEmptyQuickAddLineDraft>> = {},
) {
  return {
    value: { ...createEmptyQuickAddLineDraft(), ...over },
    onChange: vi.fn(),
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
  };
}

/**
 * Every field of the manual-entry panel reports into the draft under its
 * own key. A field wired to the wrong key (the brand landing in the name,
 * the batch in the barcode) or a scanned code that never fills the name
 * the catalogue already knows fails here.
 */
describe("DocumentQuickAddPanel — each field reports under its own key", () => {
  it("reports name, brand, barcode and batch as typed", () => {
    const props = makeProps();
    render(<DocumentQuickAddPanel {...props} />);
    fireEvent.change(screen.getByLabelText(/Item name/), {
      target: { value: "Flour" },
    });
    fireEvent.change(screen.getByLabelText("Brand"), {
      target: { value: "Mill" },
    });
    fireEvent.change(screen.getByLabelText("Barcode"), {
      target: { value: "590" },
    });
    fireEvent.change(screen.getByLabelText("Batch number"), {
      target: { value: "B-7" },
    });
    expect(props.onChange).toHaveBeenCalledWith({ name: "Flour" });
    expect(props.onChange).toHaveBeenCalledWith({ brand: "Mill" });
    expect(props.onChange).toHaveBeenCalledWith({ barcode: "590" });
    expect(props.onChange).toHaveBeenCalledWith({ batch_number: "B-7" });
  });

  it("reports the expiry date and the unit chosen", () => {
    const props = makeProps();
    render(<DocumentQuickAddPanel {...props} />);
    fireEvent.change(screen.getByLabelText("Expiry date"), {
      target: { value: "2027-01-31" },
    });
    expect(props.onChange).toHaveBeenCalledWith({ expiry_date: "2027-01-31" });
    fireEvent.click(screen.getByRole("button", { name: "pick kg" }));
    expect(props.onChange).toHaveBeenCalledWith({ uom_id: "uom-kg" });
  });

  it("closes without submitting from Cancel", () => {
    const props = makeProps();
    render(<DocumentQuickAddPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(props.onCancel).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).not.toHaveBeenCalled();
  });
});

describe("DocumentQuickAddPanel — a scanned code fills what the catalogue knows", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(lookupProductByBarcode).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fills an empty name from the product the code names", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue({
      name: "Rye flour",
      brand: null,
      sku: "RF-1",
      uom_id: "uom-kg",
      product_template_id: "pt-1",
    } as unknown as Awaited<ReturnType<typeof lookupProductByBarcode>>);
    const props = makeProps({ barcode: "5901234" });
    render(<DocumentQuickAddPanel {...props} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(lookupProductByBarcode).toHaveBeenCalledWith("5901234");
    expect(props.onChange).toHaveBeenCalledWith({
      name: "Rye flour",
      brand: "",
      sku: "RF-1",
      uom_id: "uom-kg",
      product_template_id: "pt-1",
    });
  });

  it("keeps a name the reader already typed", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue({
      name: "Rye flour",
      product_template_id: "pt-1",
    } as unknown as Awaited<ReturnType<typeof lookupProductByBarcode>>);
    const props = makeProps({ barcode: "5901234", name: "My flour" });
    render(<DocumentQuickAddPanel {...props} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(props.onChange).not.toHaveBeenCalled();
  });

  it("looks up only the last code when it changes before the pause ends", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue(null);
    const props = makeProps({ barcode: "111" });
    const { rerender } = render(<DocumentQuickAddPanel {...props} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    rerender(
      <DocumentQuickAddPanel
        {...props}
        value={{ ...props.value, barcode: "222" }}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(lookupProductByBarcode).toHaveBeenCalledTimes(1);
    expect(lookupProductByBarcode).toHaveBeenCalledWith("222");
  });
});
