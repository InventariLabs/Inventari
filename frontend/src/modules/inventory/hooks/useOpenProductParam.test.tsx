import { act, renderHook } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useOpenProductParam } from "./useOpenProductParam";

function hookAt(address: string) {
  return renderHook(
    () => ({ open: useOpenProductParam(), location: useLocation() }),
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
});
