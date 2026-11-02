import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useConfirm } from "./useConfirm";

describe("useConfirm", () => {
  it("starts with dialog closed", () => {
    const { result } = renderHook(() => useConfirm());
    expect(result.current.confirmDialogProps.open).toBe(false);
  });

  it("confirm() opens dialog with provided options", async () => {
    const { result } = renderHook(() => useConfirm());

    act(() => {
      result.current.confirm({
        title: "Delete item?",
        message: "This cannot be undone.",
        confirmLabel: "Delete",
        variant: "danger",
      });
    });

    expect(result.current.confirmDialogProps.open).toBe(true);
    expect(result.current.confirmDialogProps.title).toBe("Delete item?");
    expect(result.current.confirmDialogProps.message).toBe(
      "This cannot be undone.",
    );
    expect(result.current.confirmDialogProps.confirmLabel).toBe("Delete");
    expect(result.current.confirmDialogProps.variant).toBe("danger");
  });

  it("passes hideConfirm through to the dialog", () => {
    // An informational question (nothing left to confirm) is asked through
    // this hook too — the page keeps one dialog, and the flag has to reach it.
    const { result } = renderHook(() => useConfirm());

    act(() => {
      result.current.confirm({
        title: "In use",
        message: "Cannot delete while products point here.",
        hideConfirm: true,
      });
    });

    expect(result.current.confirmDialogProps.hideConfirm).toBe(true);
  });

  it("onConfirm resolves promise with true and closes dialog", async () => {
    const { result } = renderHook(() => useConfirm());

    let resolved: boolean | undefined;
    act(() => {
      result.current
        .confirm({ title: "Sure?", message: "Yes?" })
        .then((v) => (resolved = v));
    });

    act(() => {
      result.current.confirmDialogProps.onConfirm();
    });

    // Allow microtask to flush
    await Promise.resolve();

    expect(resolved).toBe(true);
    expect(result.current.confirmDialogProps.open).toBe(false);
  });

  it("onCancel resolves promise with false and closes dialog", async () => {
    const { result } = renderHook(() => useConfirm());

    let resolved: boolean | undefined;
    act(() => {
      result.current
        .confirm({ title: "Sure?", message: "Yes?" })
        .then((v) => (resolved = v));
    });

    act(() => {
      result.current.confirmDialogProps.onCancel();
    });

    await Promise.resolve();

    expect(resolved).toBe(false);
    expect(result.current.confirmDialogProps.open).toBe(false);
  });
});
