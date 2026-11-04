import { act, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useOpenProductParam } from "./useOpenProductParam";

function hookAt(address: string) {
  return renderHook(() => useOpenProductParam(), {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[address]}>{children}</MemoryRouter>
    ),
  });
}

describe("useOpenProductParam — the link that asks for the date", () => {
  it("opens at the expiry date when the link says so", () => {
    const { result } = hookAt("/inventory/items?open=a&at=expiry");
    expect(result.current[0]).toBe("a");
    expect(result.current[2]).toBe(true);
  });

  it("does not carry it over to the next product", () => {
    const { result } = hookAt("/inventory/items?open=a&at=expiry");
    act(() => result.current[1](null));
    act(() => result.current[1]("b"));
    expect(result.current[0]).toBe("b");
    expect(result.current[2]).toBe(false);
  });

  it("opens at the top for a plain link", () => {
    const { result } = hookAt("/inventory/items?open=a");
    expect(result.current[2]).toBe(false);
  });
});
