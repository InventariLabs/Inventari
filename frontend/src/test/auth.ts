/**
 * Sign a user into the auth store for tests that render permission-gated UI.
 *
 * Components ask `useHasPermission`, which reads the permission set /auth/me
 * returns. A test that renders such a component without a signed-in user is
 * really testing the denied state — usually not what it meant to test.
 */
import { act } from "@testing-library/react";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";

const BASE_USER: User = {
  id: "current-user",
  email: "user@example.com",
  full_name: "Test User",
  preferred_language: "en",
  role: "user",
  is_active: true,
  is_superuser: false,
  is_blocked: false,
  permissions: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

/** A plain user holding exactly these permission keys — no role bypass. */
export function signInWith(
  permissions: string[],
  overrides: Partial<User> = {},
): User {
  const user: User = { ...BASE_USER, permissions, ...overrides };
  // act-wrapped: afterEach helpers run before RTL's cleanup, so a store
  // write to a still-mounted component lands outside act and the run
  // spams "not wrapped in act" warnings.
  act(() => {
    useAuthStore.setState({ user, isAuthenticated: true });
  });
  return user;
}

export function signOut(): void {
  act(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false });
  });
}
