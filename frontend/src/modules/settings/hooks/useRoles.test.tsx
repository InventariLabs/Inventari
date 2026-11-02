import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { QueryWrapper } from "@/test/queryWrapper";
import {
  useCreateRole,
  useDeleteRole,
  usePermissionCatalog,
  useRenameRole,
  useRoleMembers,
  useRoles,
  useUpdateRolePermissions,
} from "./useRoles";

const refreshUser = vi.fn();

vi.mock("@/store/authStore", () => ({
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({ refreshUser }),
  }),
}));

/**
 * The roles hooks speak to the right endpoint with the right body, and a
 * write refreshes the rights of the session that made it. A wrong URL or a
 * dropped field here reads as "the role saved" on a screen that sent the
 * server something else.
 */
describe("role queries", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists every role", async () => {
    server.use(
      http.get("/api/v1/roles", () =>
        HttpResponse.json(onePage([{ id: "r1", name: "Packer" }])),
      ),
    );
    const { result } = renderHook(() => useRoles(), { wrapper: QueryWrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "r1", name: "Packer" }]);
  });

  it("does not ask the server while disabled", async () => {
    const seen = vi.fn();
    server.use(
      http.get("/api/v1/roles", () => {
        seen();
        return HttpResponse.json(onePage([]));
      }),
    );
    const { result } = renderHook(() => useRoles(false), {
      wrapper: QueryWrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(seen).not.toHaveBeenCalled();
  });

  it("fetches the holders of a role only once one is named", async () => {
    server.use(
      http.get("/api/v1/roles/r1/members", () =>
        HttpResponse.json(onePage([{ id: "u1", username: "ann" }])),
      ),
    );
    const idle = renderHook(() => useRoleMembers(null), {
      wrapper: QueryWrapper,
    });
    expect(idle.result.current.fetchStatus).toBe("idle");

    const { result } = renderHook(() => useRoleMembers("r1"), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "u1", username: "ann" }]);
  });

  it("reads the permission catalog from the backend", async () => {
    const catalog = {
      system: [],
      modules: [{ module: "maker", permissions: [] }],
    };
    server.use(
      http.get("/api/v1/roles/permission-catalog", () =>
        HttpResponse.json(catalog),
      ),
    );
    const { result } = renderHook(() => usePermissionCatalog(), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(catalog);
  });
});

describe("role mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates a role with its name and permissions", async () => {
    let body: unknown;
    server.use(
      http.post("/api/v1/roles", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "r2", name: "Picker" });
      }),
    );
    const { result } = renderHook(() => useCreateRole(), {
      wrapper: QueryWrapper,
    });
    await act(() =>
      result.current.mutateAsync({
        name: "Picker",
        permissions: ["items:read"],
      }),
    );
    expect(body).toEqual({ name: "Picker", permissions: ["items:read"] });
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("puts the permission list on the role's own path", async () => {
    let body: unknown;
    server.use(
      http.put("/api/v1/roles/r1/permissions", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "r1", name: "Packer" });
      }),
    );
    const { result } = renderHook(() => useUpdateRolePermissions(), {
      wrapper: QueryWrapper,
    });
    await act(() =>
      result.current.mutateAsync({ roleId: "r1", permissions: ["a", "b"] }),
    );
    expect(body).toEqual({ permissions: ["a", "b"] });
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("renames a role with a PATCH carrying only the name", async () => {
    let body: unknown;
    server.use(
      http.patch("/api/v1/roles/r1", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "r1", name: "Loader" });
      }),
    );
    const { result } = renderHook(() => useRenameRole(), {
      wrapper: QueryWrapper,
    });
    await act(() =>
      result.current.mutateAsync({ roleId: "r1", name: "Loader" }),
    );
    expect(body).toEqual({ name: "Loader" });
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("deletes a role and refreshes the session's rights", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/roles/r1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { result } = renderHook(() => useDeleteRole(), {
      wrapper: QueryWrapper,
    });
    await act(() => result.current.mutateAsync("r1"));
    expect(deleted).toHaveBeenCalledTimes(1);
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });
});
