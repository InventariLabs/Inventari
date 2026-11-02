import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Changing who holds which right refreshes every verdict computed from it.
 *
 * The approval screens ask the server whether a stage can be decided and
 * whether a request can be — answers that depend on who holds
 * `approvals:approve`. They sit under `["approvals"]` with a five-minute
 * staleTime, and neither a member's new role nor a role's new permissions
 * invalidated them: promote the only possible approver, go back to the
 * workflow list, and the yellow "a stage nobody can decide" box stayed,
 * although the API already said the opposite.
 */
vi.mock("@/store/authStore", () => ({
  useAuthStore: Object.assign(
    (selector?: (s: unknown) => unknown) => {
      const state = { refreshUser: vi.fn() };
      return selector ? selector(state) : state;
    },
    { getState: () => ({ refreshUser: vi.fn() }) },
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    put: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    patch: vi.fn().mockResolvedValue({ data: { id: "r-1" } }),
    delete: vi.fn().mockResolvedValue({ data: undefined }),
  },
}));

/**
 * A client that records what each mutation invalidates. Read from the
 * calls, not from the cache: a query nobody observes is collected, and a
 * check over the cached verdicts then passes on an empty list.
 */
function recordingClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const verdictsRefreshed = () =>
    invalidate.mock.calls.some(
      ([filters]) => filters?.queryKey?.[0] === queryKeys.approvals.all[0],
    );
  return { wrapper, verdictsRefreshed };
}

describe("a change of rights refreshes the approval verdicts", () => {
  it("after a member's role changes", async () => {
    const { useChangeMemberRole } = await import("./useOrganization");
    const { wrapper, verdictsRefreshed } = recordingClient();
    const { result } = renderHook(() => useChangeMemberRole(), { wrapper });

    result.current.mutate({ userId: "u-1", role: "manager" });

    await waitFor(() => expect(verdictsRefreshed()).toBe(true));
  });

  it("after a member is removed", async () => {
    const { useRemoveMember } = await import("./useOrganization");
    const { wrapper, verdictsRefreshed } = recordingClient();
    const { result } = renderHook(() => useRemoveMember(), { wrapper });

    result.current.mutate("u-1");

    await waitFor(() => expect(verdictsRefreshed()).toBe(true));
  });

  it("after a role's permissions change", async () => {
    const { useUpdateRolePermissions } = await import("./useRoles");
    const { wrapper, verdictsRefreshed } = recordingClient();
    const { result } = renderHook(() => useUpdateRolePermissions(), {
      wrapper,
    });

    result.current.mutate({
      roleId: "r-1",
      permissions: ["approvals:approve"],
    });

    await waitFor(() => expect(verdictsRefreshed()).toBe(true));
  });

  it("after a role is deleted", async () => {
    const { useDeleteRole } = await import("./useRoles");
    const { wrapper, verdictsRefreshed } = recordingClient();
    const { result } = renderHook(() => useDeleteRole(), { wrapper });

    result.current.mutate("r-1");

    await waitFor(() => expect(verdictsRefreshed()).toBe(true));
  });
});
