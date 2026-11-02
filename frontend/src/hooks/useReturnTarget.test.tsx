import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { useReturnTarget } from "./useReturnTarget";

function target(state: unknown): string | undefined {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[{ pathname: "/x", state }]}>
      {children}
    </MemoryRouter>
  );
  return renderHook(() => useReturnTarget(), { wrapper }).result.current;
}

describe("useReturnTarget", () => {
  it("returns the in-app path the linking page named", () => {
    expect(target({ backTo: "/warehouse/todo" })).toBe("/warehouse/todo");
  });

  it("has no target when the screen was opened directly", () => {
    expect(target(null)).toBeUndefined();
  });

  it("refuses anything that is not an in-app path", () => {
    expect(target({ backTo: "https://evil.example" })).toBeUndefined();
    expect(target({ backTo: "//evil.example" })).toBeUndefined();
    expect(target({ backTo: 3 })).toBeUndefined();
  });
});
