import { act, renderHook } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { useQuickAddLine, type QuickAddCatalogue } from "./useQuickAddLine";
import type { ReceiptDraftLine } from "@/modules/warehouse/components/documentFormShared";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/productTemplates", () => ({
  productTemplatesApi: { create: vi.fn() },
}));

const appendLine = vi.fn<(line: ReceiptDraftLine) => void>();

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

function setup(catalogue?: QuickAddCatalogue) {
  const { result } = renderHook(() => useQuickAddLine(appendLine, catalogue), {
    wrapper,
  });
  return result;
}

describe("useQuickAddLine — submit", () => {
  beforeEach(() => {
    appendLine.mockClear();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
  });

  // An emptied quantity field used to fall back to 1 through
  // `Number(value) || 1` — a line nobody meant got appended as a single
  // piece, silently. The draft now holds null while the field is empty, and
  // submit says so instead of guessing a number.
  it("refuses to add a line whose quantity field is empty", async () => {
    const result = setup();
    act(() => {
      result.current.setQuickAddDraft((draft) => ({
        ...draft,
        name: "Sugar",
        quantity: null,
      }));
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(appendLine).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("adds a line with the fraction exactly as it was typed", async () => {
    const result = setup();
    act(() => {
      result.current.setQuickAddDraft((draft) => ({
        ...draft,
        name: "Sugar",
        quantity: 12.5,
      }));
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(appendLine).toHaveBeenCalledTimes(1);
    expect(appendLine.mock.calls[0][0].quantity).toBe(12.5);
  });
});

// A receipt puts products into stock, not words: the panel there makes the
// product it describes, and the line it adds names that product.
describe("useQuickAddLine — on a receipt", () => {
  const typedLine: ReceiptDraftLine = {
    _key: "typed",
    name: "Dell lap",
    quantity: 3,
    uom_id: "uom-pcs",
    batch_number: "B-7",
    expiry_date: "",
    notes: "",
    unit_price: "3000",
    tax_rate: "",
  };
  const replaceLine = vi.fn<(key: string, line: ReceiptDraftLine) => void>();

  beforeEach(() => {
    appendLine.mockClear();
    replaceLine.mockClear();
    vi.mocked(toast.error).mockClear();
    vi.mocked(productTemplatesApi.create).mockReset();
  });

  it("makes the typed name a product and puts it in the typed line's place", async () => {
    vi.mocked(productTemplatesApi.create).mockResolvedValue({
      id: "tpl-new",
    } as Awaited<ReturnType<typeof productTemplatesApi.create>>);
    const result = setup({
      namesAProduct: true,
      lines: [typedLine],
      replaceLine,
    });

    act(() => {
      result.current.openForTypedLine?.("typed", "Dell laptop");
    });
    // What the typed line already said is not asked a second time.
    expect(result.current.quickAddDraft).toMatchObject({
      name: "Dell laptop",
      quantity: 3,
      uom_id: "uom-pcs",
      batch_number: "B-7",
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(productTemplatesApi.create).toHaveBeenCalledWith(
      "Dell laptop",
      "uom-pcs",
      { brand: "", barcode: "" },
    );
    expect(replaceLine).toHaveBeenCalledTimes(1);
    expect(replaceLine.mock.calls[0][0]).toBe("typed");
    expect(replaceLine.mock.calls[0][1]).toMatchObject({
      product_template_id: "tpl-new",
      name: "Dell laptop",
      quantity: 3,
    });
    expect(appendLine).not.toHaveBeenCalled();
  });

  // A saved typed line made a product came back without its code, brand and
  // serial: the panel opened blank on them and the line it handed back
  // replaced the old one whole.
  it("keeps the typed line's code, brand and serial through the making", async () => {
    vi.mocked(productTemplatesApi.create).mockResolvedValue({
      id: "tpl-new",
    } as Awaited<ReturnType<typeof productTemplatesApi.create>>);
    const result = setup({
      namesAProduct: true,
      lines: [
        {
          ...typedLine,
          brand: "Dell",
          barcode: "5901234123457",
          sku: "DL-7",
          serial_number: "SN-42",
        },
      ],
      replaceLine,
    });

    act(() => {
      result.current.openForTypedLine?.("typed", "Dell laptop");
    });
    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(productTemplatesApi.create).toHaveBeenCalledWith(
      "Dell laptop",
      "uom-pcs",
      { brand: "Dell", barcode: "5901234123457" },
    );
    expect(replaceLine.mock.calls[0][1]).toMatchObject({
      brand: "Dell",
      barcode: "5901234123457",
      sku: "DL-7",
      serial_number: "SN-42",
    });
  });

  it("asks for the unit before it makes a product", async () => {
    const result = setup({ namesAProduct: true, lines: [], replaceLine });
    act(() => {
      result.current.openQuickAdd({ name: "Loose bolts", barcode: "123" });
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(productTemplatesApi.create).not.toHaveBeenCalled();
    expect(appendLine).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("keeps the panel when the product could not be made", async () => {
    vi.mocked(productTemplatesApi.create).mockRejectedValue(new Error("no"));
    const result = setup({ namesAProduct: true, lines: [], replaceLine });
    act(() => {
      result.current.openQuickAdd({ name: "Loose bolts", uom_id: "uom-pcs" });
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(appendLine).not.toHaveBeenCalled();
    expect(result.current.quickAddOpen).toBe(true);
    expect(result.current.quickAddDraft.name).toBe("Loose bolts");
  });

  it("takes a product a scanned code already names as it is", async () => {
    const result = setup({ namesAProduct: true, lines: [], replaceLine });
    act(() => {
      result.current.openQuickAdd({
        name: "Gouda",
        barcode: "590",
        product_template_id: "tpl-gouda",
      });
    });

    await act(async () => {
      await result.current.handleQuickAddSubmit();
    });

    expect(productTemplatesApi.create).not.toHaveBeenCalled();
    expect(appendLine.mock.calls[0][0].product_template_id).toBe("tpl-gouda");
  });
});
