import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useKeysetPaging } from "./useKeysetPaging";

describe("useKeysetPaging", () => {
  it("opens on the first page with no cursor", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));

    expect(result.current.page).toBe(0);
    expect(result.current.cursor).toBeUndefined();
  });

  it("goes forward by the cursor the page on screen carried", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));

    act(() => result.current.goNext("c1"));
    expect(result.current.page).toBe(1);
    expect(result.current.cursor).toBe("c1");

    act(() => result.current.goNext("c2"));
    expect(result.current.page).toBe(2);
    expect(result.current.cursor).toBe("c2");
  });

  it("goes back to a page already seen with the cursor it was opened by", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));
    act(() => result.current.goNext("c1"));
    act(() => result.current.goNext("c2"));

    act(() => result.current.goPrev());
    expect(result.current.page).toBe(1);
    expect(result.current.cursor).toBe("c1");

    act(() => result.current.goPrev());
    expect(result.current.page).toBe(0);
    expect(result.current.cursor).toBeUndefined();
  });

  it("replaces the cursors beyond a page it went back to when it goes forward again", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));
    act(() => result.current.goNext("c1"));
    act(() => result.current.goNext("c2"));
    act(() => result.current.goPrev());

    act(() => result.current.goNext("c2-again"));

    expect(result.current.page).toBe(2);
    expect(result.current.cursor).toBe("c2-again");
  });

  it("stays where it is when the page on screen has no next cursor", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));

    act(() => result.current.goNext(null));
    act(() => result.current.goNext(undefined));

    expect(result.current.page).toBe(0);
  });

  it("never goes back past the first page", () => {
    const { result } = renderHook(() => useKeysetPaging({ q: "a" }));

    act(() => result.current.goPrev());

    expect(result.current.page).toBe(0);
  });

  it("starts again from the first page when the question changes", () => {
    const { result, rerender } = renderHook(({ q }) => useKeysetPaging({ q }), {
      initialProps: { q: "a" },
    });
    act(() => result.current.goNext("c1"));
    expect(result.current.page).toBe(1);

    rerender({ q: "b" });

    expect(result.current.page).toBe(0);
    expect(result.current.cursor).toBeUndefined();
  });

  it("keeps its place when the question is the same in a new object", () => {
    const { result, rerender } = renderHook(({ q }) => useKeysetPaging({ q }), {
      initialProps: { q: "a" },
    });
    act(() => result.current.goNext("c1"));

    rerender({ q: "a" });

    expect(result.current.page).toBe(1);
    expect(result.current.cursor).toBe("c1");
  });
});
