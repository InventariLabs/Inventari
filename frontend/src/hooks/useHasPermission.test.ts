import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { useHasPermission } from "./useHasPermission";

const sampleUser: User = {
  permissions: [],
  id: "u1",
  email: "alice@example.com",
  full_name: "Alice",
  role: "user",
  is_superuser: false,
  is_active: true,
  is_blocked: false,
  preferred_language: "en",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function resetStore() {
  useAuthStore.setState({ user: null, isAuthenticated: false });
}

describe("useHasPermission", () => {
  it("returns false when there is no user", () => {
    resetStore();
    const { result } = renderHook(() => useHasPermission("admin:access"));
    expect(result.current).toBe(false);
  });

  it("returns true for an admin regardless of the permission string", () => {
    resetStore();
    act(() => {
      useAuthStore.setState({
        user: { ...sampleUser, role: "admin" },
        isAuthenticated: true,
      });
    });
    const { result } = renderHook(() => useHasPermission("admin:access"));
    expect(result.current).toBe(true);
  });

  it("returns true for a superuser", () => {
    resetStore();
    act(() => {
      useAuthStore.setState({
        user: { ...sampleUser, is_superuser: true },
        isAuthenticated: true,
      });
    });
    const { result } = renderHook(() => useHasPermission("anything:read"));
    expect(result.current).toBe(true);
  });

  it("returns false for a non-admin without cached permissions", () => {
    resetStore();
    act(() => {
      useAuthStore.setState({
        user: { ...sampleUser, role: "user" },
        isAuthenticated: true,
      });
    });
    const { result } = renderHook(() => useHasPermission("admin:access"));
    expect(result.current).toBe(false);
  });

  // Before /auth/me returned permissions the hook answered false for every
  // non-admin, so permission gating was really role gating: a manager holding
  // approvals:approve still saw the action hidden.
  describe("with the permission set from /auth/me", () => {
    function signIn(permissions: string[]) {
      resetStore();
      act(() => {
        useAuthStore.setState({
          user: { ...sampleUser, role: "user", permissions },
          isAuthenticated: true,
        });
      });
    }

    it("grants a permission the user actually holds", () => {
      signIn(["items:read", "approvals:approve"]);
      const { result } = renderHook(() =>
        useHasPermission("approvals:approve"),
      );
      expect(result.current).toBe(true);
    });

    it("denies one that is absent", () => {
      signIn(["items:read"]);
      const { result } = renderHook(() => useHasPermission("items:delete"));
      expect(result.current).toBe(false);
    });

    it("matches exactly, without prefix leniency", () => {
      signIn(["items:read"]);
      const { result } = renderHook(() => useHasPermission("items:read:all"));
      expect(result.current).toBe(false);
    });

    it("denies on an empty set rather than falling back to a bypass", () => {
      signIn([]);
      const { result } = renderHook(() => useHasPermission("items:read"));
      expect(result.current).toBe(false);
    });

    it("keeps the admin bypass even when the payload disagrees", () => {
      resetStore();
      act(() => {
        useAuthStore.setState({
          user: { ...sampleUser, role: "admin", permissions: [] },
          isAuthenticated: true,
        });
      });
      const { result } = renderHook(() => useHasPermission("items:delete"));
      expect(result.current).toBe(true);
    });
  });
});
