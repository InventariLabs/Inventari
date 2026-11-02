import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { useHasRole } from "./useHasRole";

const mockAuthState: { user: { role: string; is_superuser: boolean } | null } =
  { user: { role: "admin", is_superuser: false } };

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

describe("useHasRole", () => {
  it("returns true for an included role", () => {
    mockAuthState.user = { role: "manager", is_superuser: false };
    const { result } = renderHook(() => useHasRole(["admin", "manager"]));
    expect(result.current).toBe(true);
  });

  it("returns false for a non-included role", () => {
    mockAuthState.user = { role: "user", is_superuser: false };
    const { result } = renderHook(() => useHasRole(["admin", "manager"]));
    expect(result.current).toBe(false);
  });

  it("returns true for superuser regardless of role", () => {
    mockAuthState.user = { role: "user", is_superuser: true };
    const { result } = renderHook(() => useHasRole(["admin"]));
    expect(result.current).toBe(true);
  });

  it("returns false when no user is logged in", () => {
    mockAuthState.user = null;
    const { result } = renderHook(() => useHasRole(["admin", "manager"]));
    expect(result.current).toBe(false);
  });
});
