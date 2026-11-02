/**
 * Paging state of the shared list hook: a list that keeps showing page 3
 * after the reader narrowed it shows an empty page for a non-empty result.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useFilteredList } from "./useFilteredList";

const DEFS = { status: { default: "" } } as const;

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

function setup() {
  return renderHook(() => useFilteredList(DEFS, { limit: 20 }), { wrapper });
}

describe("useFilteredList pagination", () => {
  it("moves a page at a time and stops at the first page going back", () => {
    const { result } = setup();

    act(() => result.current.onNext());
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(40);

    act(() => result.current.onPrev());
    expect(result.current.skip).toBe(20);
    act(() => result.current.onPrev());
    act(() => result.current.onPrev());
    expect(result.current.skip).toBe(0);
  });

  it("steps by the page size the reader picked", () => {
    const { result } = setup();

    act(() => result.current.setLimit(50));
    act(() => result.current.onNext());

    expect(result.current.skip).toBe(50);
  });

  it("returns to the first page when a filter changes", () => {
    const { result } = setup();
    act(() => result.current.onNext());
    expect(result.current.skip).toBe(20);

    act(() => result.current.setFilter("status", "open"));

    expect(result.current.skip).toBe(0);
  });

  it("returns to the first page when the search settles on a new term", async () => {
    const { result } = setup();
    act(() => result.current.onNext());

    act(() => result.current.setSearchInput("rice"));

    await waitFor(() => expect(result.current.search).toBe("rice"));
    expect(result.current.skip).toBe(0);
  });

  it("resetPagination brings the reader back to the first page", () => {
    const { result } = setup();
    act(() => result.current.onNext());

    act(() => result.current.resetPagination());

    expect(result.current.skip).toBe(0);
  });
});
