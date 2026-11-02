import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { usePoLineScanner } from "./usePoLineScanner";
import { lookupProductByBarcode } from "@/modules/shared/lib/productLookup";
import type { POLineInput } from "../components/POLinesSection";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast };
});

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: () => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
    setIsCameraActive: vi.fn(),
  }),
}));

type ResolverOptions = {
  handle: (result: { action: string }, code: string) => Promise<boolean>;
  acceptUnrecognized: () => boolean;
};
const resolver = vi.hoisted(() => ({
  options: null as unknown,
  resolve: vi.fn(),
}));
vi.mock("@/hooks/useScanResolver", () => ({
  useScanResolver: (options: unknown) => {
    resolver.options = options;
    return { resolve: resolver.resolve };
  },
}));

vi.mock("@/modules/shared/lib/productLookup", () => ({
  lookupProductByBarcode: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

const options = () => resolver.options as ResolverOptions;

const LATTE = {
  product_template_id: "tpl-1",
  name: "Latte cups",
  sku: "LC-1",
  brand: null,
  image_url: null,
  uom_id: "uom-1",
};

/** Runs the updater the hook hands over against `lines`. */
function linesAfter(
  onAdd: ReturnType<typeof vi.fn>,
  lines: POLineInput[],
): POLineInput[] {
  const updater = onAdd.mock.calls.at(-1)?.[0] as (
    l: POLineInput[],
  ) => POLineInput[];
  return updater(lines);
}

/**
 * A scanned product becomes a line on the order, and a second scan of it
 * adds one to that line instead of a duplicate; a location or a document
 * scanned here is handed back to the resolver, and an unknown code says so.
 * A scanner that duplicated lines, put a location onto the order or failed
 * silently breaks one of these.
 */
describe("usePoLineScanner — what a scan does to the order's lines", () => {
  beforeEach(() => vi.clearAllMocks());

  it("adds a recognized product as a new line with the scanned barcode", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue(
      LATTE as unknown as Awaited<ReturnType<typeof lookupProductByBarcode>>,
    );
    const onAdd = vi.fn();
    renderHook(() => usePoLineScanner({ onAddOrIncrementLine: onAdd }));

    let handled: boolean | undefined;
    await act(async () => {
      handled = await options().handle({ action: "show_item" }, "5901234");
    });

    expect(handled).toBe(true);
    const lines = linesAfter(onAdd, []);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({
      product_template_id: "tpl-1",
      name: "Latte cups",
      sku: "LC-1",
      barcode: "5901234",
      quantity_ordered: 1,
      uom_id: "uom-1",
    });
    expect(toast.success).toHaveBeenCalledWith("purchase_orders:form.addedOne");
  });

  it("counts a second scan of the same product onto its line", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue(
      LATTE as unknown as Awaited<ReturnType<typeof lookupProductByBarcode>>,
    );
    const onAdd = vi.fn();
    renderHook(() => usePoLineScanner({ onAddOrIncrementLine: onAdd }));
    await act(async () => {
      await options().handle({ action: "show_item" }, "5901234");
    });

    const other = {
      id: "l-2",
      product_template_id: "tpl-9",
      quantity_ordered: 4,
    } as POLineInput;
    const existing = {
      id: "l-1",
      product_template_id: "tpl-1",
      quantity_ordered: 2,
    } as POLineInput;
    const lines = linesAfter(onAdd, [existing, other]);
    expect(lines).toHaveLength(2);
    expect(lines[0].quantity_ordered).toBe(3);
    expect(lines[1].quantity_ordered).toBe(4);
  });

  it("says a code is unknown when no product answers to it", async () => {
    vi.mocked(lookupProductByBarcode).mockRejectedValue(new Error("404"));
    const onAdd = vi.fn();
    renderHook(() => usePoLineScanner({ onAddOrIncrementLine: onAdd }));
    await act(async () => {
      await options().handle({ action: "show_item" }, "000");
    });
    expect(onAdd).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("form.scanUnknown");
  });

  it("hands a location or a document back instead of adding it", async () => {
    const onAdd = vi.fn();
    renderHook(() => usePoLineScanner({ onAddOrIncrementLine: onAdd }));
    let handled: boolean[] = [];
    await act(async () => {
      handled = [
        await options().handle({ action: "set_storage_context" }, "LOC-1"),
        await options().handle({ action: "open_document" }, "DOC-1"),
      ];
    });
    expect(handled).toEqual([false, false]);
    expect(lookupProductByBarcode).not.toHaveBeenCalled();
  });

  it("toasts the failure when adding the line throws", async () => {
    vi.mocked(lookupProductByBarcode).mockResolvedValue(
      LATTE as unknown as Awaited<ReturnType<typeof lookupProductByBarcode>>,
    );
    const onAdd = vi.fn(() => {
      throw new Error("broken");
    });
    const { result } = renderHook(() =>
      usePoLineScanner({ onAddOrIncrementLine: onAdd }),
    );
    await act(async () => {
      await options().handle({ action: "show_item" }, "5901234");
    });
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.scanLoading).toBe(false);
  });

  it("names an unrecognized code and sends a scanned code to the resolver", () => {
    const { result } = renderHook(() =>
      usePoLineScanner({ onAddOrIncrementLine: vi.fn() }),
    );
    expect(options().acceptUnrecognized()).toBe(true);
    expect(toast).toHaveBeenCalledWith("form.scanUnknown");

    result.current.handleCodeScanned("ABC");
    expect(resolver.resolve).toHaveBeenCalledWith("ABC");
  });
});
