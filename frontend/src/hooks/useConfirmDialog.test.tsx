import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useConfirmDialog } from "./useConfirmDialog";

describe("useConfirmDialog", () => {
  it("initializes with dialog closed", () => {
    const { result } = renderHook(() => useConfirmDialog());

    expect(result.current.dialogState.isOpen).toBe(false);
    expect(result.current.dialogState.title).toBe("");
    expect(result.current.dialogState.message).toBe("");
  });

  it("exposes dialogState, showConfirm, and closeDialog", () => {
    const { result } = renderHook(() => useConfirmDialog());

    expect(result.current).toHaveProperty("dialogState");
    expect(result.current).toHaveProperty("showConfirm");
    expect(result.current).toHaveProperty("closeDialog");
  });

  it("showConfirm opens dialog and returns promise", async () => {
    const { result } = renderHook(() => useConfirmDialog());

    act(() => {
      const promise = result.current.showConfirm({
        title: "Test",
        message: "Test message",
        onConfirm: () => {},
      });

      expect(promise).toBeInstanceOf(Promise);
    });

    expect(result.current.dialogState.isOpen).toBe(true);
    expect(result.current.dialogState.title).toBe("Test");
  });

  it("closeDialog closes the dialog", () => {
    const { result } = renderHook(() => useConfirmDialog());

    act(() => {
      result.current.showConfirm({
        title: "Test",
        message: "Test",
        onConfirm: () => {},
      });
    });

    expect(result.current.dialogState.isOpen).toBe(true);

    act(() => {
      result.current.closeDialog();
    });

    expect(result.current.dialogState.isOpen).toBe(false);
  });
});
