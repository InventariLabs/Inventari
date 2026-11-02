import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { usePagination } from "./usePagination";

describe("usePagination", () => {
  it("steps forward and back by one page, and never past either end", () => {
    const { result } = renderHook(() => usePagination(25, 10));

    act(() => result.current.onPrev());
    expect(result.current.skip).toBe(0);

    act(() => result.current.onNext());
    expect(result.current.skip).toBe(10);
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(20);
    // 30 would start a page with no rows in it.
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(20);

    act(() => result.current.onPrev());
    expect(result.current.skip).toBe(10);
  });

  it("returns to the first page on reset", () => {
    const { result } = renderHook(() => usePagination(25, 10));
    act(() => result.current.onNext());

    act(() => result.current.reset());

    expect(result.current.skip).toBe(0);
  });

  it("jumps to a zero-based page and refuses a negative one", () => {
    const { result } = renderHook(() => usePagination(100, 10));

    act(() => result.current.setPage(3));
    expect(result.current.skip).toBe(30);

    act(() => result.current.setPage(-2));
    expect(result.current.skip).toBe(0);
  });

  it("goes back to the first page when the total changes under a filter", () => {
    const { result, rerender } = renderHook(
      ({ total }) => usePagination(total, 10),
      { initialProps: { total: 50 } },
    );
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(10);

    rerender({ total: 12 });

    expect(result.current.skip).toBe(0);
  });
});
