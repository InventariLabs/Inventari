import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useDiscardGuard } from "./useDiscardGuard";
import { useFormGuardStore } from "@/store/formGuardStore";

afterEach(() => useFormGuardStore.getState().setDirtyForm(null));

describe("useDiscardGuard", () => {
  it("closes a clean sheet at once", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useDiscardGuard(false, onClose, "The order form"),
    );

    act(() => result.current.requestClose());

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(result.current.dialogProps.open).toBe(false);
  });

  it("asks before it closes a filled-in sheet", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useDiscardGuard(true, onClose, "The order form"),
    );

    act(() => result.current.requestClose());

    expect(onClose).not.toHaveBeenCalled();
    expect(result.current.dialogProps.open).toBe(true);
  });

  it("reports a filled-in sheet to the navigation gate until it is clean or gone", () => {
    // The header sits partly above the sheet overlay: a click on its logo is
    // an exit the sheet's own close paths never see, so the draft has to be
    // known to the shell-wide gate as well.
    const { rerender, unmount } = renderHook(
      ({ dirty }) => useDiscardGuard(dirty, vi.fn(), "The order form"),
      { initialProps: { dirty: true } },
    );
    expect(useFormGuardStore.getState().dirtyForm).toBe("The order form");

    rerender({ dirty: false });
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    rerender({ dirty: true });
    unmount();
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();
  });
});
