import { act, renderHook } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useItemFilters } from "./useItemFilters";
import { useOpenProductParam } from "./useOpenProductParam";

function hookAt(address: string) {
  return renderHook(
    () => {
      const filters = useItemFilters();
      return {
        filters,
        open: useOpenProductParam(filters.writeParams),
        location: useLocation(),
        navigate: useNavigate(),
      };
    },
    {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={[address]}>{children}</MemoryRouter>
      ),
    },
  );
}

describe("useOpenProductParam — the link that asks for the date", () => {
  it("does not carry the request over to the next product", () => {
    const { result } = hookAt("/inventory/items?open=a&at=expiry");
    expect(result.current.open[0]).toBe("a");

    act(() => result.current.open[1](null));
    expect(result.current.location.search).toBe("");

    act(() => result.current.open[1]("b"));
    expect(result.current.location.search).toBe("?open=b");
  });

  it("keeps a chip tapped in the same moment as the product opened", () => {
    const { result } = hookAt("/inventory/items");

    act(() => {
      result.current.filters.setLowStockFilter(true);
      result.current.open[1]("a");
    });

    const params = new URLSearchParams(result.current.location.search);
    expect(params.get("open")).toBe("a");
    expect(params.get("filter")).toBe("low-stock");
  });

  it("keeps the chip when the product is closed again in the same moment", () => {
    const { result } = hookAt("/inventory/items?open=a");

    act(() => {
      result.current.open[1](null);
      result.current.filters.setLowStockFilter(true);
    });

    const params = new URLSearchParams(result.current.location.search);
    expect(params.has("open")).toBe(false);
    expect(params.get("filter")).toBe("low-stock");
  });
});

describe("useOpenProductParam — Back closes the dialog", () => {
  it("adds an entry for a product opened from the list, and closing pops it", () => {
    const { result } = hookAt("/inventory/items");

    act(() => result.current.open[1]("a"));
    expect(result.current.open[0]).toBe("a");
    expect(result.current.location.search).toBe("?open=a");

    act(() => result.current.open[1](null));
    expect(result.current.open[0]).toBeNull();
    expect(result.current.location.search).toBe("");
  });

  it("closes the dialog when the browser goes back", () => {
    const { result } = hookAt("/inventory/items");
    act(() => result.current.open[1]("a"));

    act(() => result.current.navigate(-1));

    expect(result.current.open[0]).toBeNull();
    expect(result.current.location.pathname).toBe("/inventory/items");
    expect(result.current.location.search).toBe("");
  });
});
