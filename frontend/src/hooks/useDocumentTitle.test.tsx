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
});
