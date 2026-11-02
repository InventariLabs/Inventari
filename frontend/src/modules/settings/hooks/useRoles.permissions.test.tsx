import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * A role edit reaches the session that made it.
 *
 * `authStore.user.permissions` is filled once, at boot (`checkAuth`), and
 * every permission gate on every screen reads it from there. Editing a role
 * invalidated the `["roles"]` query and nothing else, so an administrator
 * who granted or revoked a permission on their own role kept working
 * against the rights they had when they logged in — for the rest of a
 * session that can last days. The screens looked right and refused the
 * wrong things.
 */
const refreshUser = vi.fn();

vi.mock("@/store/authStore", () => ({
  useAuthStore: Object.assign(
    (selector?: (s: unknown) => unknown) => {
      const state = { refreshUser };
      return selector ? selector(state) : state;
    },
    { getState: () => ({ refreshUser }) },
  ),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    put: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    patch: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    delete: vi.fn().mockResolvedValue({ data: undefined }),
  },
}));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
);

describe("role mutations refresh the editing session's permissions", () => {
  beforeEach(() => refreshUser.mockClear());

  it("refreshes after a permission change", async () => {
    const { useUpdateRolePermissions } = await import("./useRoles");
    const { result } = renderHook(() => useUpdateRolePermissions(), {
      wrapper,
    });

    result.current.mutate({ roleId: "r-1", permissions: ["items:write"] });

    await waitFor(() => expect(refreshUser).toHaveBeenCalled());
  });

  it("refreshes after a role is deleted", async () => {
    const { useDeleteRole } = await import("./useRoles");
    const { result } = renderHook(() => useDeleteRole(), { wrapper });

    result.current.mutate("r-1");

    await waitFor(() => expect(refreshUser).toHaveBeenCalled());
  });
});
