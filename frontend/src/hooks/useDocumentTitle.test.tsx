import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useDocumentTitle } from "./useDocumentTitle";

describe("useDocumentTitle", () => {
  afterEach(() => {
    document.title = "Inventari";
  });

  it("names the tab after the page", () => {
    renderHook(() => useDocumentTitle("Products"));
    expect(document.title).toBe("Products · Inventari");
  });

  it("follows the title when it changes", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Products" },
    });
    rerender({ title: "Produkty" });
    expect(document.title).toBe("Produkty · Inventari");
  });

  it("goes back to the plain name when the page unmounts", () => {
    const { unmount } = renderHook(() => useDocumentTitle("Products"));
    unmount();
    expect(document.title).toBe("Inventari");
  });

  it("leaves the title alone while the page has none yet", () => {
    renderHook(() => useDocumentTitle(undefined));
    expect(document.title).toBe("Inventari");
  });

  it("hands the tab back to the holder that is still mounted", () => {
    renderHook(() => useDocumentTitle("Purchase Orders"));
    const inner = renderHook(() => useDocumentTitle("Order not found"));
    expect(document.title).toBe("Order not found · Inventari");
    inner.unmount();
    expect(document.title).toBe("Purchase Orders · Inventari");
  });

  it("keeps the newer title when an older holder unmounts late", () => {
    const older = renderHook(() => useDocumentTitle("Order not found"));
    renderHook(() => useDocumentTitle("Purchase Orders"));
    older.unmount();
    expect(document.title).toBe("Purchase Orders · Inventari");
  });

  it("keeps the inner holder on the tab when both are re-titled", () => {
    const outer = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Purchase Orders" },
    });
    const inner = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Order not found" },
    });
    outer.rerender({ title: "Zamówienia zakupu" });
    inner.rerender({ title: "Nie znaleziono zamówienia" });
    outer.rerender({ title: "Zamówienia" });
    expect(document.title).toBe("Nie znaleziono zamówienia · Inventari");
  });
});
