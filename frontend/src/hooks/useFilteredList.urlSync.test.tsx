/**
 * The URL is an input the reader can change without remounting the list.
 *
 * A row of the product list links to `?location_id=…` on the route it already
 * sits on. React Router swaps the search string and unmounts nothing, so a
 * filter read only in a `useState` initialiser never saw the new value: the
 * link registered as a click and the list came back unchanged, which is
 * indistinguishable from a dead link. Opening the very same address in a new
 * tab filtered correctly, which is what kept the bug hidden.
 */
import { act } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useFilteredList } from "./useFilteredList";

const DEFS = {
  storageFilter: { default: "", urlKey: "location_id" },
  categoryFilter: { default: "", urlKey: "category_id" },
  expiringFilter: { default: false, urlKey: "filter", urlValue: "expiring" },
  expiredFilter: { default: false, urlKey: "filter", urlValue: "expired" },
  unsynced: { default: "" },
} as const;

/** The hook under test, plus the navigate a row link would call. */
function useSubject() {
  return {
    list: useFilteredList(DEFS),
    navigate: useNavigate(),
  };
}

const wrapperFor = (initial: string) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>;
  };

describe("useFilteredList — filters answer to the URL after mount", () => {
  it("reads a param that was there on arrival", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items?location_id=bay-3"),
    });

    expect(result.current.list.values.storageFilter).toBe("bay-3");
  });

  it("applies a param that arrives from an in-app link", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items"),
    });
    expect(result.current.list.values.storageFilter).toBe("");

    act(() => result.current.navigate("/items?location_id=bay-3"));

    expect(result.current.list.values.storageFilter).toBe("bay-3");
    expect(result.current.list.isNarrowed).toBe(true);
  });

  it("clears the filter when the param leaves the URL again", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items?location_id=bay-3"),
    });

    act(() => result.current.navigate("/items"));

    expect(result.current.list.values.storageFilter).toBe("");
    expect(result.current.list.isNarrowed).toBe(false);
  });

  it("reads the boolean form keyed by its param value", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items"),
    });

    act(() => result.current.navigate("/items?filter=expiring"));
    expect(result.current.list.values.expiringFilter).toBe(true);

    act(() => result.current.navigate("/items?filter=expired"));
    expect(result.current.list.values.expiringFilter).toBe(false);
  });

  it("keeps a filter the reader set by hand when an unrelated param changes", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items"),
    });

    // The reader narrows by category through the panel: no param is written,
    // so following a storage link must not quietly undo that choice.
    act(() => result.current.list.setFilter("categoryFilter", "dairy"));
    act(() => result.current.navigate("/items?location_id=bay-3"));

    expect(result.current.list.values.categoryFilter).toBe("dairy");
    expect(result.current.list.values.storageFilter).toBe("bay-3");
  });

  it("leaves filters that sync to no param alone", () => {
    const { result } = renderHook(useSubject, {
      wrapper: wrapperFor("/items"),
    });

    act(() => result.current.list.setFilter("unsynced", "kept"));
    act(() => result.current.navigate("/items?location_id=bay-3"));

    expect(result.current.list.values.unsynced).toBe("kept");
  });
});

function useWritableSubject() {
  return {
    list: useFilteredList(DEFS, { syncToUrl: true }),
    location: useLocation(),
    navigate: useNavigate(),
  };
}

describe("useFilteredList — explicit URL writes", () => {
  // The router commits an address in a transition, so a second tap can arrive
  // while the screen still renders the address from before the first one. On a
  // busy phone the first chip dropped out of the address, and the sync back
  // from the address then switched it off under the reader's thumb.
  it("keeps a chip ticked before the address of the last one was rendered", async () => {
    const { result } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items"),
    });
    await act(async () => {
      result.current.list.setFilter("expiringFilter", true);
      await Promise.resolve();
      result.current.list.setFilter("expiredFilter", true);
    });
    expect(
      new URLSearchParams(result.current.location.search).get("filter"),
    ).toBe("expiring,expired");
    expect(result.current.list.values.expiringFilter).toBe(true);
    expect(result.current.list.values.expiredFilter).toBe(true);
  });

  it("builds on an address someone else navigated to, not on its own last write", () => {
    const { result } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items"),
    });
    act(() => result.current.list.setFilter("expiringFilter", true));
    act(() => result.current.navigate("/items?location_id=bay-3"));
    act(() => result.current.list.setFilter("expiredFilter", true));
    const params = new URLSearchParams(result.current.location.search);
    expect(params.get("location_id")).toBe("bay-3");
    expect(params.get("filter")).toBe("expired");
  });

  it("clears a linked filter from the address and keeps it cleared on reload", () => {
    const { result, unmount } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items?location_id=bay-3&unrelated=kept"),
    });
    act(() => result.current.list.setFilter("storageFilter", ""));
    expect(result.current.location.search).toBe("?unrelated=kept");
    const address =
      result.current.location.pathname + result.current.location.search;
    unmount();
    const reloaded = renderHook(useWritableSubject, {
      wrapper: wrapperFor(address),
    });
    expect(reloaded.result.current.list.values.storageFilter).toBe("");
  });

  it("writes string and named boolean filters while preserving other parameters", () => {
    const { result } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items?unrelated=kept"),
    });
    act(() => result.current.list.setFilter("storageFilter", "bay-4"));
    act(() => result.current.list.setFilter("expiringFilter", true));
    const params = new URLSearchParams(result.current.location.search);
    expect(params.get("location_id")).toBe("bay-4");
    expect(params.get("filter")).toBe("expiring");
    expect(params.get("unrelated")).toBe("kept");
    act(() => result.current.list.setFilter("expiringFilter", false));
    expect(
      new URLSearchParams(result.current.location.search).has("filter"),
    ).toBe(false);
  });

  it("keeps several chips sharing one parameter on together, and after a reload", () => {
    const { result, unmount } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items"),
    });
    act(() => result.current.list.setFilter("expiringFilter", true));
    act(() => result.current.list.setFilter("expiredFilter", true));
    expect(result.current.list.values.expiringFilter).toBe(true);
    expect(result.current.list.values.expiredFilter).toBe(true);
    const address =
      result.current.location.pathname + result.current.location.search;
    unmount();
    const reloaded = renderHook(useWritableSubject, {
      wrapper: wrapperFor(address),
    });
    expect(reloaded.result.current.list.values.expiringFilter).toBe(true);
    expect(reloaded.result.current.list.values.expiredFilter).toBe(true);
    act(() => reloaded.result.current.list.setFilter("expiringFilter", false));
    expect(reloaded.result.current.list.values.expiredFilter).toBe(true);
    expect(reloaded.result.current.location.search).toBe("?filter=expired");
  });

  it("continues to follow navigation without writing over the destination", () => {
    const { result } = renderHook(useWritableSubject, {
      wrapper: wrapperFor("/items"),
    });
    act(() => result.current.list.setFilter("storageFilter", "bay-4"));
    act(() => result.current.navigate("/items?location_id=bay-5"));
    expect(result.current.list.values.storageFilter).toBe("bay-5");
    expect(result.current.location.search).toBe("?location_id=bay-5");
  });
});
