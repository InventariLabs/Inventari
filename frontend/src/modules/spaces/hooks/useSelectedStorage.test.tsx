import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useSelectedStorage } from "./useSelectedStorage";

const FLOOR = [
  { id: "home", name: "Home", parent_id: null },
  { id: "pantry", name: "Pantry", parent_id: "home" },
];

describe("useSelectedStorage", () => {
  it("is a failed read when the way down to the place could not be read", async () => {
    serveLocations(FLOOR);
    server.use(
      http.get("/api/v1/locations/:id/breadcrumb", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useSelectedStorage("pantry", true), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.summary?.name).toBe("Pantry");
  });

  it("reads the unscoped lookup again on refetch when the lists keep the place off", async () => {
    const requests = serveLocations([
      ...FLOOR,
      {
        id: "rack",
        name: "Server rack",
        parent_id: null,
        context_tag: "equipment",
      },
    ]);
    const { result } = renderHook(() => useSelectedStorage("rack", true), {
      wrapper: QueryWrapper,
    });
    await waitFor(() =>
      expect(result.current.withheld?.name).toBe("Server rack"),
    );
    const asked = () =>
      requests.filter((r) => r.getAll("ids").includes("rack")).length;
    const before = asked();

    act(() => result.current.refetch());

    await waitFor(() => expect(asked()).toBeGreaterThanOrEqual(before + 2));
  });
});
