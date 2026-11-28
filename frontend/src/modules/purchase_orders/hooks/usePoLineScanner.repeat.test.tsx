import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePoLineScanner } from "./usePoLineScanner";

const scan = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/labels", () => ({ labelsApi: { scan } }));
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: () => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
    setIsCameraActive: vi.fn(),
  }),
}));
vi.mock("@/modules/shared/lib/productLookup", () => ({
  lookupProductByBarcode: vi.fn().mockResolvedValue({
    product_template_id: "tpl-1",
    name: "Latte cups",
  }),
}));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

describe("usePoLineScanner — a second piece read during the lookup", () => {
  it("adds one to the order for each read of the same code", async () => {
    const answers: (() => void)[] = [];
    scan.mockImplementation(
      () =>
        new Promise((resolve) => {
          answers.push(() => resolve({ action: "show_stock_actions" }));
        }),
    );
    const onAdd = vi.fn();
    const { result } = renderHook(() =>
      usePoLineScanner({ onAddOrIncrementLine: onAdd }),
    );

    await act(async () => {
      result.current.handleCodeScanned("5901234123457");
      result.current.handleCodeScanned("5901234123457");
    });
    await act(async () => answers[0]());
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => answers[1]());

    expect(onAdd).toHaveBeenCalledTimes(2);
  });
});
