import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useExistingLocations } from "./useExistingLocations";

const FLOOR = [
  { id: "home", name: "Home", parent_id: null },
  { id: "pantry", name: "Pantry", parent_id: "home" },
];

describe("useExistingLocations", () => {
  it("reads the top level and the level under the parent", async () => {
    serveLocations(FLOOR);
    const { result } = renderHook(() => useExistingLocations("home"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.rows.map((row) => row.name).sort()).toEqual([
        "Home",
        "Pantry",
      ]),
    );
    expect(result.current.topLevelTotal).toBe(1);
    expect(result.current.isError).toBe(false);
  });

  it("is a failed read when the level under the parent failed, not a shorter list of names", async () => {
    serveLocations(FLOOR);
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        new URL(request.url).searchParams.has("parent_id")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );
    const { result } = renderHook(() => useExistingLocations("home"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
