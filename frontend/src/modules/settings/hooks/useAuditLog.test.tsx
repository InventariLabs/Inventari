import { describe, it, expect } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { useAuditLog, useAuditTargetTypes } from "./useAuditLog";

/**
 * The journal asks the server for exactly the filters it was given, and the
 * target-type filter lists what the log holds, not a hard-coded set.
 */
describe("audit log hooks", () => {
  it("sends the chosen filters as query parameters and omits the empty ones", async () => {
    let search = "";
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    const { result } = renderHook(
      () => useAuditLog({ target_type: "storage", actor: "human", limit: 25 }),
      { wrapper: QueryWrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const params = new URLSearchParams(search);
    expect(params.get("target_type")).toBe("storage");
    expect(params.get("actor")).toBe("human");
    expect(params.get("limit")).toBe("25");
    expect(params.has("since")).toBe(false);
    expect(params.has("cursor")).toBe(false);
  });

  it("lists the target types the log actually records", async () => {
    server.use(
      http.get("/api/v1/audit-log/target-types", () =>
        HttpResponse.json(["item", "storage"]),
      ),
    );
    const { result } = renderHook(() => useAuditTargetTypes(), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(["item", "storage"]);
  });
});
