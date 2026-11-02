import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAutoResetFlag } from "./useAutoResetFlag";

describe("useAutoResetFlag", () => {
  it("arms on and resets after the delay", async () => {
    const { result } = renderHook(() => useAutoResetFlag(20));
    const [, arm] = result.current;

    act(() => {
      arm();
    });
    expect(result.current[0]).toBe(true);

    await waitFor(() => expect(result.current[0]).toBe(false));
  });

  it("re-arming inside the window does not reset early", () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useAutoResetFlag(30));
      const [, arm] = result.current;

      act(() => {
        arm();
      });
      act(() => {
        vi.advanceTimersByTime(15);
      });
      act(() => {
        arm();
      });
      // 35 ms: behind the moment the first window would close (30 ms) and
      // before the second one does (45 ms). An assertion before 30 ms cannot
      // tell a taken-back first window from a leaked one. Fake timers keep
      // the reset inside act() — real waits let it fire outside under load.
      act(() => {
        vi.advanceTimersByTime(20);
      });
      expect(result.current[0]).toBe(true);
      act(() => {
        vi.advanceTimersByTime(10);
      });
      expect(result.current[0]).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("takes the pending timer back when the component goes away", () => {
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
    const { result, unmount } = renderHook(() => useAutoResetFlag(5000));
    const [, arm] = result.current;

    act(() => {
      arm();
    });
    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
    clearTimeoutSpy.mockRestore();
  });
});
