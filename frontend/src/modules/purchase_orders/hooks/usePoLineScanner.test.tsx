import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePoLineScanner } from "./usePoLineScanner";

const camera = vi.hoisted(() => ({
  restartCamera: vi.fn(),
  setIsCameraActive: vi.fn(),
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: () => ({
    isCameraActive: true,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: camera.restartCamera,
    setIsCameraActive: camera.setIsCameraActive,
  }),
}));
vi.mock("@/hooks/useScanResolver", () => ({
  useScanResolver: () => ({ resolve: vi.fn() }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

describe("usePoLineScanner", () => {
  beforeEach(() => vi.clearAllMocks());

  it("starts the camera when the panel is opened and stops it on close", () => {
    const { result } = renderHook(() =>
      usePoLineScanner({ onAddOrIncrementLine: vi.fn() }),
    );
    expect(camera.restartCamera).not.toHaveBeenCalled();

    act(() => result.current.toggleScan());
    expect(result.current.scanOpen).toBe(true);
    expect(camera.restartCamera).toHaveBeenCalledTimes(1);

    act(() => result.current.toggleScan());
    expect(result.current.scanOpen).toBe(false);
    expect(camera.setIsCameraActive).toHaveBeenCalledWith(false);

    act(() => result.current.toggleScan());
    expect(camera.restartCamera).toHaveBeenCalledTimes(2);
  });
});
